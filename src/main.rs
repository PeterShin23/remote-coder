mod chat_adapter;
mod config;
mod error;
mod models;
mod session_manager;

use config::load_config;
use session_manager::SessionManager;
use std::sync::Arc;
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Load .env file if present
    dotenv::dotenv().ok();

    // Initialize logging
    tracing_subscriber::fmt()
        .with_env_filter(
            EnvFilter::from_default_env()
                .add_directive("cockpit_coder=debug".parse()?)
                .add_directive("info".parse()?),
        )
        .init();

    tracing::info!("Starting Cockpit Coder daemon v{}", env!("CARGO_PKG_VERSION"));

    // Load configuration
    let config = Arc::new(load_config()?);
    tracing::info!(
        "Loaded {} projects, {} agents",
        config.projects.len(),
        config.agents.len()
    );

    // Log project details
    for (id, project) in &config.projects {
        tracing::info!(
            "  Project '{}': {:?} (agent: {})",
            id,
            project.path,
            project.default_agent_id
        );
    }

    // Initialize session manager
    let session_manager = Arc::new(SessionManager::new());
    tracing::info!("Session manager initialized");

    // TODO: Initialize Slack adapter (Pass 2)
    // TODO: Initialize router (Pass 4)
    // TODO: Initialize process manager (Pass 3)
    // TODO: Start Slack connection (Pass 2)

    // Setup graceful shutdown
    tracing::info!("Daemon started. Press Ctrl+C to shutdown.");
    tokio::signal::ctrl_c().await?;
    tracing::info!("Shutting down...");

    // TODO: Cleanup active sessions
    let active_sessions = session_manager.list_active();
    if !active_sessions.is_empty() {
        tracing::info!("Cleaning up {} active sessions", active_sessions.len());
    }

    tracing::info!("Shutdown complete");
    Ok(())
}
