use thiserror::Error;

/// Main error type for Cockpit Coder
#[derive(Error, Debug)]
pub enum CockpitError {
    #[error("Project not found for channel: {0}")]
    ProjectNotFound(String),

    #[error("Session not found: {0}")]
    SessionNotFound(uuid::Uuid),

    #[error("Agent not found: {0}")]
    AgentNotFound(String),

    #[error("Command not found: {0}")]
    CommandNotFound(String),

    #[error("Process error: {0}")]
    ProcessError(String),

    #[error("Configuration error: {0}")]
    ConfigError(String),

    #[error("Slack error: {0}")]
    SlackError(String),

    #[error("GitHub error: {0}")]
    GitHubError(String),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("YAML parse error: {0}")]
    YamlError(#[from] serde_yaml::Error),
}

/// Convenience Result type
pub type Result<T> = std::result::Result<T, CockpitError>;
