export interface UserInfo {
  id: string;
  name: string;
  memory_enabled: boolean;
  provider: string;
}

export interface ConversationInfo {
  id: string;
  title: string;
  character_id: string;
}

export interface ChatMessage {
  id: string;
  role: string;
  content: string;
}

export interface MemoryItem {
  id: string;
  content: string;
  kind: string;
  status: string;
  revision: number;
  pinned: boolean;
  source_type: string;
}

export interface MemoryList {
  items: MemoryItem[];
}

export interface MemoryVersion {
  revision: number;
  content: string;
  reason: string;
}

export interface MemoryEvidence {
  id: string;
  content: string;
  conversation_id: string;
}

export interface MemoryDetail extends MemoryItem {
  versions: MemoryVersion[];
  evidence: MemoryEvidence[];
}

export interface StreamPayload {
  request_id: string;
  sequence: number;
  text?: string;
  message?: string;
  memory_ids?: string[];
}

export interface DeletionJob {
  id: string;
  status: string;
  scope?: string;
}

export interface SettingsResult {
  memory_enabled: boolean;
}
