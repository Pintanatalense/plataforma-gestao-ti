import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface DeliveryItem {
  id: string;
  event_id: string;
  event_type: string | null;
  channel: string;
  status: string;
  priority: string;
  recipient_email: string | null;
  address: string;
  title: string | null;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  next_attempt_at: string;
  created_at: string;
  sent_at: string | null;
}

export interface DeliveryDetail extends DeliveryItem {
  attempt_log: { attempt_no: number; started_at: string; finished_at: string | null; outcome: string; error: string | null }[];
  event_payload: Record<string, unknown>;
}

export interface DeliveryFilters {
  channel?: string;
  status?: string;
  event_type?: string;
  recipient?: string;
  date_from?: string;
  date_to?: string;
  limit?: number;
  offset?: number;
}

export interface RuleItem {
  id: string;
  code: string | null;
  is_system: boolean;
  name: string;
  enabled: boolean;
  event_type: string;
  condition: Record<string, unknown>;
  audience: string[];
  channels: string[];
  template_code: string;
}

export type RuleInput = Omit<RuleItem, 'id' | 'code' | 'is_system'>;

export interface RulesResponse {
  items: RuleItem[];
  options: { channels: string[]; templates: string[]; selectors: string[] };
}

export interface SimulatedDelivery {
  rule: string;
  recipient_email: string;
  channel: string;
  title: string | null;
  send_at: string;
}

export interface ChannelHealth {
  channel: string;
  enabled: boolean;
  circuit_open: boolean;
  pending: number;
  dead: number;
  sent: number;
  last_sent_at: string | null;
  oldest_pending_at: string | null;
  failures_last_hour: number;
  attempts_last_hour: number;
  last_error: string | null;
  last_error_at: string | null;
}

export interface HealthResponse {
  worker: { status: 'healthy' | 'stale' | 'stopped'; beat_at: string | null; totals: Record<string, unknown> };
  events_waiting: { count: number; oldest_at: string | null };
  channels: ChannelHealth[];
}

export interface JobItem {
  name: string;
  schedule: string;
  enabled: boolean;
  next_run_at: string;
  last_run_at: string | null;
  last_status: string | null;
  last_error: string | null;
}

export interface TelegramConfig {
  enabled: boolean;
  bot_token: string;
  bot_username: string | null;
  app_base_url: string;
}

export type WhatsAppProvider = 'evolution' | 'meta';

export interface WhatsAppConfig {
  enabled: boolean;
  provider: WhatsAppProvider;
  instance_name: string;
  /** O servidor tem a chave da Evolution (EVOLUTION_API_KEY): sem ela o provedor não funciona. */
  evolution_ready: boolean;
  access_token: string;
  app_secret: string;
  phone_number_id: string;
  graph_version: string;
  template_name: string;
  template_language: string;
  app_base_url: string;
  display_phone: string | null;
  verified_name: string | null;
  verify_token: string | null;
  webhook_path: string;
}

export interface SlackConfig {
  enabled: boolean;
  bot_token: string;
  signing_secret: string;
  app_base_url: string;
  bot_name: string | null;
  team_name: string | null;
  events_path: string;
}

export type SlackConfigInput = Pick<SlackConfig, 'enabled' | 'bot_token' | 'signing_secret' | 'app_base_url'>;

export type WhatsAppConfigInput = Omit<WhatsAppConfig, 'display_phone' | 'verified_name' | 'verify_token' | 'webhook_path' | 'evolution_ready'>;

/** Estado da conexão do número (Evolution). */
export interface WhatsAppStatus {
  provider: WhatsAppProvider;
  state: 'open' | 'connecting' | 'close' | 'unconfigured' | 'error' | 'not_applicable';
  detail: string;
  display_phone: string | null;
}

export interface WhatsAppConnect extends WhatsAppStatus {
  qr_base64: string | null;
  pairing_code: string | null;
  count: number | null;
}

@Injectable({ providedIn: 'root' })
export class NotificationsAdminService {
  private http = inject(HttpClient);
  private base = '/api/v1/notifications/admin';

  listDeliveries(filters: DeliveryFilters = {}): Observable<{ total: number; items: DeliveryItem[] }> {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== null && value !== '') params = params.set(key, String(value));
    }
    return this.http.get<{ total: number; items: DeliveryItem[] }>(`${this.base}/deliveries`, { params });
  }

  getDelivery(id: string): Observable<DeliveryDetail> {
    return this.http.get<DeliveryDetail>(`${this.base}/deliveries/${id}`);
  }

  resend(id: string): Observable<{ id: string; status: string }> {
    return this.http.post<{ id: string; status: string }>(`${this.base}/deliveries/${id}/resend`, {});
  }

  cancel(id: string): Observable<{ id: string; status: string }> {
    return this.http.post<{ id: string; status: string }>(`${this.base}/deliveries/${id}/cancel`, {});
  }

  listRules(): Observable<RulesResponse> {
    return this.http.get<RulesResponse>(`${this.base}/rules`);
  }

  createRule(rule: RuleInput): Observable<RuleItem> {
    return this.http.post<RuleItem>(`${this.base}/rules`, rule);
  }

  updateRule(id: string, rule: RuleInput): Observable<RuleItem> {
    return this.http.put<RuleItem>(`${this.base}/rules/${id}`, rule);
  }

  deleteRule(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/rules/${id}`);
  }

  simulate(body: { event_type: string; priority: string; payload: Record<string, unknown> }): Observable<{ deliveries: SimulatedDelivery[] }> {
    return this.http.post<{ deliveries: SimulatedDelivery[] }>(`${this.base}/rules/simulate`, body);
  }

  health(): Observable<HealthResponse> {
    return this.http.get<HealthResponse>(`${this.base}/channels`);
  }

  testChannel(channel: string): Observable<{ channel: string; ok: boolean; detail: string }> {
    return this.http.post<{ channel: string; ok: boolean; detail: string }>(`${this.base}/channels/${channel}/test`, {});
  }

  getTelegramConfig(): Observable<TelegramConfig> {
    return this.http.get<TelegramConfig>('/api/v1/notifications/telegram/config');
  }

  saveTelegramConfig(config: Pick<TelegramConfig, 'enabled' | 'bot_token' | 'app_base_url'>): Observable<TelegramConfig> {
    return this.http.put<TelegramConfig>('/api/v1/notifications/telegram/config', config);
  }

  getWhatsAppConfig(): Observable<WhatsAppConfig> {
    return this.http.get<WhatsAppConfig>('/api/v1/notifications/whatsapp/config');
  }

  saveWhatsAppConfig(config: WhatsAppConfigInput): Observable<WhatsAppConfig> {
    return this.http.put<WhatsAppConfig>('/api/v1/notifications/whatsapp/config', config);
  }

  whatsAppStatus(): Observable<WhatsAppStatus> {
    return this.http.get<WhatsAppStatus>('/api/v1/notifications/whatsapp/status');
  }

  /** `refresh`: repetição automática para girar o QR (não gera nova linha de auditoria). */
  whatsAppConnect(refresh = false): Observable<WhatsAppConnect> {
    return this.http.post<WhatsAppConnect>('/api/v1/notifications/whatsapp/connect', {}, refresh ? { params: { refresh: 'true' } } : {});
  }

  whatsAppDisconnect(): Observable<WhatsAppStatus> {
    return this.http.post<WhatsAppStatus>('/api/v1/notifications/whatsapp/disconnect', {});
  }

  getSlackConfig(): Observable<SlackConfig> {
    return this.http.get<SlackConfig>('/api/v1/notifications/slack/config');
  }

  saveSlackConfig(config: SlackConfigInput): Observable<SlackConfig> {
    return this.http.put<SlackConfig>('/api/v1/notifications/slack/config', config);
  }

  listJobs(): Observable<{ items: JobItem[] }> {
    return this.http.get<{ items: JobItem[] }>(`${this.base}/jobs`);
  }

  setJobEnabled(name: string, enabled: boolean): Observable<{ name: string; enabled: boolean }> {
    return this.http.patch<{ name: string; enabled: boolean }>(`${this.base}/jobs/${name}`, { enabled });
  }

  runJob(name: string): Observable<unknown> {
    return this.http.post(`${this.base}/jobs/${name}/run`, {});
  }
}
