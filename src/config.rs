use crate::error::{CockpitError, Result};
use crate::models::{Agent, GitHubRepoConfig, Project};
use serde::Deserialize;
use std::collections::HashMap;
use std::env;
use std::fs;
use std::path::{Path, PathBuf};

/// Main configuration for Cockpit Coder
pub struct Config {
    pub projects: HashMap<String, Project>,
    pub agents: HashMap<String, Agent>,
    pub slack_bot_token: String,
    pub slack_app_token: String,
    pub slack_allowed_user_id: String,
    pub github_token: Option<String>,
}

#[derive(Debug, Deserialize)]
struct ProjectsYaml {
    base_dir: PathBuf,
    projects: HashMap<String, ProjectConfigYaml>,
}

#[derive(Debug, Deserialize)]
struct ProjectConfigYaml {
    path: PathBuf,
    default_agent: String,
    github: Option<GitHubRepoConfig>,
}

#[derive(Debug, Deserialize)]
struct AgentsYaml {
    agents: HashMap<String, Agent>,
}

impl Config {
    /// Get a project by its channel name
    pub fn get_project_by_channel(&self, channel: &str) -> Result<&Project> {
        self.projects
            .get(channel)
            .ok_or_else(|| CockpitError::ProjectNotFound(channel.to_string()))
    }

    /// Get a project by its ID
    pub fn get_project(&self, project_id: &str) -> Result<&Project> {
        self.projects
            .get(project_id)
            .ok_or_else(|| CockpitError::ProjectNotFound(project_id.to_string()))
    }

    /// Get an agent by its ID
    pub fn get_agent(&self, agent_id: &str) -> Result<&Agent> {
        self.agents
            .get(agent_id)
            .ok_or_else(|| CockpitError::AgentNotFound(agent_id.to_string()))
    }
}

/// Load configuration from YAML files and environment variables
pub fn load_config() -> Result<Config> {
    // Load environment variables (required)
    let slack_bot_token = env::var("SLACK_BOT_TOKEN")
        .map_err(|_| CockpitError::ConfigError("SLACK_BOT_TOKEN not set".to_string()))?;

    let slack_app_token = env::var("SLACK_APP_TOKEN")
        .map_err(|_| CockpitError::ConfigError("SLACK_APP_TOKEN not set".to_string()))?;

    let slack_allowed_user_id = env::var("SLACK_ALLOWED_USER_ID")
        .map_err(|_| CockpitError::ConfigError("SLACK_ALLOWED_USER_ID not set".to_string()))?;

    // GitHub token is optional
    let github_token = env::var("GITHUB_TOKEN").ok();

    // Load projects.yaml
    let projects = load_projects("config/projects.yaml")?;

    // Load agents.yaml
    let agents = load_agents("config/agents.yaml")?;

    Ok(Config {
        projects,
        agents,
        slack_bot_token,
        slack_app_token,
        slack_allowed_user_id,
        github_token,
    })
}

fn load_projects(path: &str) -> Result<HashMap<String, Project>> {
    let content = fs::read_to_string(path)
        .map_err(|e| CockpitError::ConfigError(format!("Failed to read {}: {}", path, e)))?;

    let yaml: ProjectsYaml = serde_yaml::from_str(&content)?;

    let mut projects = HashMap::new();

    for (id, config) in yaml.projects {
        // Resolve full path: base_dir + path
        let full_path = yaml.base_dir.join(&config.path);

        // Validate that the path exists
        if !full_path.exists() {
            tracing::warn!(
                "Project '{}' path does not exist: {:?}",
                id,
                full_path
            );
        }

        let project = Project {
            id: id.clone(),
            channel_name: id.clone(), // Channel name matches project ID
            path: full_path,
            default_agent_id: config.default_agent,
            github: config.github,
        };

        projects.insert(id, project);
    }

    Ok(projects)
}

fn load_agents(path: &str) -> Result<HashMap<String, Agent>> {
    let content = fs::read_to_string(path)
        .map_err(|e| CockpitError::ConfigError(format!("Failed to read {}: {}", path, e)))?;

    let yaml: AgentsYaml = serde_yaml::from_str(&content)?;

    Ok(yaml.agents)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_project_lookup() {
        let mut projects = HashMap::new();
        projects.insert(
            "test-project".to_string(),
            Project {
                id: "test-project".to_string(),
                channel_name: "test-project".to_string(),
                path: PathBuf::from("/tmp/test"),
                default_agent_id: "claude-code".to_string(),
                github: None,
            },
        );

        let config = Config {
            projects,
            agents: HashMap::new(),
            slack_bot_token: "test".to_string(),
            slack_app_token: "test".to_string(),
            slack_allowed_user_id: "test".to_string(),
            github_token: None,
        };

        assert!(config.get_project_by_channel("test-project").is_ok());
        assert!(config.get_project_by_channel("nonexistent").is_err());
    }
}
