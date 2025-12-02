use crate::error::Result;
use async_trait::async_trait;

/// Trait for chat platform adapters (Slack, Discord, etc.)
///
/// This abstraction allows us to support multiple chat platforms
/// while keeping the core logic platform-agnostic.
#[async_trait]
pub trait ChatAdapter: Send + Sync {
    /// Send a message to a channel/thread
    ///
    /// # Arguments
    /// * `channel` - The channel ID
    /// * `thread_ts` - The thread timestamp (for threaded messages)
    /// * `text` - The message text
    async fn send_message(&self, channel: &str, thread_ts: &str, text: &str) -> Result<()>;

    /// Start listening for messages
    ///
    /// This should be a long-running operation that continuously
    /// listens for and processes incoming messages.
    async fn start(&self) -> Result<()>;
}
