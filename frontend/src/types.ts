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
  recommended?: boolean;
}
export interface DockerImage {
  id: string;
  tags: string[];
  size: number;
  blocked_reasons: string[];
}
export interface Workload {
  id: string;
  kind: string;
  username: string;
  user_id: string;
  status: string;
  command: string;
  requested_gpus: number;
  requested_gpu_indices: number[] | null;
  time_limit_seconds: number;
  approval_status: string;
  approval_reason: string;
  approval_note: string;
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
  external_busy: boolean;
  metrics: {
    name: string;
    uuid: string;
    pci_bus_id: string;
    driver_version: string;
    memory_total_mb: number | null;
    memory_used_mb: number | null;
    memory_free_mb: number | null;
    utilization_percent: number | null;
    memory_utilization_percent: number | null;
    temperature_c: number | null;
    power_w: number | null;
    power_limit_w: number | null;
    fan_percent: number | null;
    graphics_clock_mhz: number | null;
    memory_clock_mhz: number | null;
    compute_process_count: number;
  } | null;
}
export interface ContainerWorkspace {
  mode: "container";
  host_paths: Record<"workspace" | "results" | "scratch" | "datasets", string>;
  host_uid: number;
  host_gid: number;
  host_import_command: string;
  state: string;
  route_path: string;
  container_id: string | null;
  environment: Environment;
  venv: string;
}
export interface HostWorkspace {
  mode: "host";
  state: string;
  route_path: string;
  container_id: null;
  host_user: string;
  host_home: string;
  host_uid: number;
  host_gid: number;
  host_python: string;
  error_message: string;
}
export type Workspace = ContainerWorkspace | HostWorkspace;
export interface QueueItem {
  id: string;
  kind: string;
  status: string;
  requested_gpus: number;
  requested_gpu_indices: number[] | null;
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
