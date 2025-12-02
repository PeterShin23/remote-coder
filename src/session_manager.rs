use crate::error::{CockpitError, Result};
use crate::models::{PullRequestRef, Session, SessionStatus};
use chrono::{DateTime, Duration, Utc};
use std::collections::HashMap;
use std::sync::{Arc, RwLock};
use uuid::Uuid;

/// Manages all active and ended sessions
pub struct SessionManager {
    sessions: Arc<RwLock<HashMap<Uuid, Session>>>,
    thread_index: Arc<RwLock<HashMap<(String, String), Uuid>>>,
    pr_refs: Arc<RwLock<HashMap<Uuid, PullRequestRef>>>,
}

impl SessionManager {
    pub fn new() -> Self {
        Self {
            sessions: Arc::new(RwLock::new(HashMap::new())),
            thread_index: Arc::new(RwLock::new(HashMap::new())),
            pr_refs: Arc::new(RwLock::new(HashMap::new())),
        }
    }

    /// Create a new session
    pub fn create_session(
        &self,
        project_id: String,
        channel: String,
        thread_ts: String,
        agent_id: String,
    ) -> Result<Session> {
        let session = Session {
            id: Uuid::new_v4(),
            project_id,
            slack_channel: channel.clone(),
            slack_thread_ts: thread_ts.clone(),
            active_agent_id: agent_id,
            status: SessionStatus::Active,
            created_at: Utc::now(),
            updated_at: Utc::now(),
        };

        let session_id = session.id;

        // Store session
        {
            let mut sessions = self.sessions.write().unwrap();
            sessions.insert(session_id, session.clone());
        }

        // Index by (channel, thread_ts)
        {
            let mut index = self.thread_index.write().unwrap();
            index.insert((channel, thread_ts), session_id);
        }

        tracing::info!(
            "Created session {} for project {} in channel/thread",
            session_id,
            session.project_id
        );

        Ok(session)
    }

    /// Get a session by ID
    pub fn get_session(&self, id: Uuid) -> Result<Session> {
        let sessions = self.sessions.read().unwrap();
        sessions
            .get(&id)
            .cloned()
            .ok_or_else(|| CockpitError::SessionNotFound(id))
    }

    /// Get a session by (channel, thread_ts)
    pub fn get_by_thread(&self, channel: &str, thread_ts: &str) -> Result<Session> {
        let index = self.thread_index.read().unwrap();
        let session_id = index
            .get(&(channel.to_string(), thread_ts.to_string()))
            .ok_or_else(|| {
                CockpitError::SessionNotFound(Uuid::nil()) // Use nil UUID for "not found by thread"
            })?;

        self.get_session(*session_id)
    }

    /// Update the active agent for a session
    pub fn update_active_agent(&self, id: Uuid, agent_id: String) -> Result<()> {
        let mut sessions = self.sessions.write().unwrap();

        let session = sessions
            .get_mut(&id)
            .ok_or_else(|| CockpitError::SessionNotFound(id))?;

        session.active_agent_id = agent_id;
        session.updated_at = Utc::now();

        Ok(())
    }

    /// Update session status
    pub fn update_status(&self, id: Uuid, status: SessionStatus) -> Result<()> {
        let mut sessions = self.sessions.write().unwrap();

        let session = sessions
            .get_mut(&id)
            .ok_or_else(|| CockpitError::SessionNotFound(id))?;

        session.status = status;
        session.updated_at = Utc::now();

        Ok(())
    }

    /// List all active sessions
    pub fn list_active(&self) -> Vec<Session> {
        let sessions = self.sessions.read().unwrap();
        sessions
            .values()
            .filter(|s| s.status == SessionStatus::Active)
            .cloned()
            .collect()
    }

    /// Clean up ended sessions older than the given duration
    /// Returns the number of sessions removed
    pub fn cleanup_ended(&self, older_than: Duration) -> usize {
        let cutoff = Utc::now() - older_than;
        let mut count = 0;

        // Get IDs to remove
        let ids_to_remove: Vec<Uuid> = {
            let sessions = self.sessions.read().unwrap();
            sessions
                .iter()
                .filter(|(_, s)| s.status == SessionStatus::Ended && s.updated_at < cutoff)
                .map(|(id, _)| *id)
                .collect()
        };

        // Remove sessions
        {
            let mut sessions = self.sessions.write().unwrap();
            for id in &ids_to_remove {
                sessions.remove(id);
                count += 1;
            }
        }

        // Remove from thread index
        {
            let mut index = self.thread_index.write().unwrap();
            index.retain(|_, session_id| !ids_to_remove.contains(session_id));
        }

        // Remove PR refs
        {
            let mut pr_refs = self.pr_refs.write().unwrap();
            for id in &ids_to_remove {
                pr_refs.remove(id);
            }
        }

        count
    }

    /// Associate a PR with a session
    pub fn set_pr_ref(&self, pr_ref: PullRequestRef) -> Result<()> {
        let mut pr_refs = self.pr_refs.write().unwrap();
        pr_refs.insert(pr_ref.session_id, pr_ref);
        Ok(())
    }

    /// Get the PR associated with a session
    pub fn get_pr_ref(&self, session_id: Uuid) -> Result<PullRequestRef> {
        let pr_refs = self.pr_refs.read().unwrap();
        pr_refs
            .get(&session_id)
            .cloned()
            .ok_or_else(|| CockpitError::SessionNotFound(session_id))
    }
}

impl Default for SessionManager {
    fn default() -> Self {
        Self::new()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_session_lifecycle() {
        let manager = SessionManager::new();

        // Create session
        let session = manager
            .create_session(
                "test-project".to_string(),
                "test-channel".to_string(),
                "1234.5678".to_string(),
                "claude-code".to_string(),
            )
            .unwrap();

        // Get by ID
        let retrieved = manager.get_session(session.id).unwrap();
        assert_eq!(retrieved.id, session.id);

        // Get by thread
        let by_thread = manager
            .get_by_thread("test-channel", "1234.5678")
            .unwrap();
        assert_eq!(by_thread.id, session.id);

        // Update agent
        manager
            .update_active_agent(session.id, "codex-cli".to_string())
            .unwrap();
        let updated = manager.get_session(session.id).unwrap();
        assert_eq!(updated.active_agent_id, "codex-cli");

        // End session
        manager
            .update_status(session.id, SessionStatus::Ended)
            .unwrap();
        let ended = manager.get_session(session.id).unwrap();
        assert_eq!(ended.status, SessionStatus::Ended);
    }

    #[test]
    fn test_cleanup() {
        let manager = SessionManager::new();

        let session = manager
            .create_session(
                "test".to_string(),
                "channel".to_string(),
                "thread".to_string(),
                "agent".to_string(),
            )
            .unwrap();

        manager
            .update_status(session.id, SessionStatus::Ended)
            .unwrap();

        // Recent ended session should not be cleaned up
        let cleaned = manager.cleanup_ended(Duration::hours(1));
        assert_eq!(cleaned, 0);

        // Old ended session should be cleaned up
        let cleaned = manager.cleanup_ended(Duration::seconds(0));
        assert_eq!(cleaned, 1);
    }
}
