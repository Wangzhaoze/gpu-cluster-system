export interface User {
  id: string;
  username: string;
  display_name: string;
  role: "ADMIN" | "MEMBER";
  enabled: boolean;
  default_environment_id: string;
  max_gpus: number;
  max_debug_hours: number;
}
export interface Environment {
  id: string;
  name: string;
  image: string;
  image_version: string;
  description: string;
  enabled: boolean;
  available?: boolean;
}
export interface Workload {
  id: string;
  kind: string;
  username: string;
  user_id: string;
  status: string;
  command: string;
  requested_gpus: number;
  assigned_gpus: number[];
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  expires_at: string | null;
  route_path: string | null;
  exit_code: number | null;
  error_message: string | null;
  cancel_requested: boolean;
}
export interface Slot {
  gpu_index: number;
  state: string;
  owner_type: string | null;
  owner_id: string | null;
  username: string | null;
  started_at: string | null;
}
export interface Workspace {
  state: string;
  route_path: string;
  container_id: string | null;
  environment: Environment;
  venv: string;
}
export interface QueueItem {
  id: string;
  kind: string;
  status: string;
  requested_gpus: number;
  username: string;
}
export interface Variable {
  scope: string;
  key: string;
  value: string;
  is_secret: boolean;
  enabled: boolean;
}
export interface Storage {
  username: string;
  bytes: Record<string, number>;
}
export interface Audit {
  id: string;
  action: string;
  target_id: string;
  created_at: string;
  metadata: Record<string, unknown>;
}
export interface Remote {
  status: string;
  url: string | null;
}
