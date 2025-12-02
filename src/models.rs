use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::path::PathBuf;
use uuid::Uuid;

/// Represents a project (git repository) mapped to a Slack channel
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Project {
    pub id: String,
    pub channel_name: String,
    pub path: PathBuf,
    pub default_agent_id: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub github: Option<GitHubRepoConfig>,
}

/// GitHub repository configuration for PR features
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct GitHubRepoConfig {
    pub owner: String,
    pub repo: String,
    pub default_base_branch: String,
}

/// Represents a coding CLI agent (codex-cli, claude-code, gemini-cli)
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Agent {
    pub id: String,
    pub kind: AgentKind,
    pub command: Vec<String>,
    pub working_dir_mode: WorkingDirMode,
}

/// Type of agent
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum AgentKind {
    Cli,
}

/// How to determine the working directory for an agent
#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum WorkingDirMode {
    Project,
    #[serde(rename = "fixed")]
    Fixed(PathBuf),
}

/// A session represents one Slack thread where an agent is working
#[derive(Debug, Clone)]
pub struct Session {
    pub id: Uuid,
    pub project_id: String,
    pub slack_channel: String,
    pub slack_thread_ts: String,
    pub active_agent_id: String,
    pub status: SessionStatus,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

/// Status of a session
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum SessionStatus {
    Active,
    Ended,
}

/// Tracks a Pull Request associated with a session
#[derive(Debug, Clone)]
pub struct PullRequestRef {
    pub project_id: String,
    pub session_id: Uuid,
    pub number: u64,
    pub url: String,
    pub head_branch: String,
    pub base_branch: String,
    pub created_at: DateTime<Utc>,
    pub updated_at: DateTime<Utc>,
}

/// Argument definition for a .cockpit/commands file
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CommandArg {
    pub name: String,
    #[serde(rename = "type")]
    pub arg_type: String, // e.g. "string"
    pub required: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
}

/// A command defined in .cockpit/commands/*.md
#[derive(Debug, Clone)]
pub struct CommandDefinition {
    pub id: String,
    pub title: String,
    pub description: Option<String>,
    pub category: Option<String>,
    pub args: Vec<CommandArg>,
    pub body: String, // Markdown instructions
}
