import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface CsvExportRequest {
  entity_type: 'tickets' | 'users' | 'categories' | 'sectors' | 'units' | 'employees' | 'assets' | 'stock_items';
  delimiter?: string;
  include_headers?: boolean;
  date_from?: string | null;
  date_to?: string | null;
}

export interface CsvColumnMapping {
  file_column: string;
  system_field: string;
  required: boolean;
}

export interface CsvAnalysisResponse {
  filename: string;
  detected_delimiter: string;
  detected_encoding: string;
  total_rows_detected: number;
  headers: string[];
  column_mappings: CsvColumnMapping[];
  preview_rows: Record<string, any>[];
  available_system_fields: {
    field: string;
    label: string;
    required: boolean;
    description: string;
  }[];
}

export interface CsvImportExecutionRequest {
  entity_type: string;
  column_mappings: CsvColumnMapping[];
  rows: Record<string, any>[];
  on_duplicate?: 'skip' | 'update' | 'error';
  dry_run?: boolean;
}

export interface CsvImportResult {
  total_processed: number;
  success_count: number;
  error_count: number;
  skipped_count: number;
  errors: { row: number; field: string; message: string }[];
  created_ids: string[];
}

export interface DbBackup {
  id: string;
  filename: string;
  size_bytes: number;
  sha256_hash: string | null;
  status: 'PENDING' | 'SUCCESS' | 'FAILED';
  error_message: string | null;
  created_at: string;
  created_by_email: string | null;
}

export interface WhatsAppConfig {
  provider: 'MOCK' | 'EVOLUTION_API' | 'META_CLOUD_API';
  is_enabled: boolean;
  api_url: string;
  instance_name: string;
  welcome_message: string;

  // Proteção Anti-Ban e Humanização
  anti_ban_enabled: boolean;
  min_delay_seconds: number;
  max_delay_seconds: number;
  simulate_typing: boolean;
  typing_duration_seconds: number;
  max_messages_per_minute: number;
  cooldown_per_recipient_seconds: number;
  emergency_pause: boolean;
}

export interface WhatsAppConfigUpdate {
  provider?: string;
  is_enabled?: boolean;
  api_url?: string;
  api_key?: string;
  instance_name?: string;
  webhook_secret?: string;
  welcome_message?: string;

  anti_ban_enabled?: boolean;
  min_delay_seconds?: number;
  max_delay_seconds?: number;
  simulate_typing?: boolean;
  typing_duration_seconds?: number;
  max_messages_per_minute?: number;
  cooldown_per_recipient_seconds?: number;
  emergency_pause?: boolean;
}

export interface WhatsAppTemplate {
  id: string;
  name: string;
  code: string;
  category: string;
  content: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface WhatsAppOutboxItem {
  id: string;
  to_phone: string;
  message: string;
  status: 'PENDING' | 'SENDING' | 'SENT' | 'FAILED' | 'CANCELLED';
  priority: number;
  ticket_id: string | null;
  template_id: string | null;
  scheduled_for: string | null;
  sent_at: string | null;
  attempts: number;
  max_attempts: number;
  last_error: string | null;
  created_at: string;
}

export interface WhatsAppOutboxStats {
  pending_count: number;
  sent_today_count: number;
  failed_count: number;
  sent_last_minute: number;
  anti_ban_enabled: boolean;
  emergency_pause: boolean;
  min_delay_seconds: number;
  max_delay_seconds: number;
  simulate_typing: boolean;
  max_messages_per_minute: number;
  cooldown_per_recipient_seconds: number;
}

@Injectable({
  providedIn: 'root'
})
export class AdminService {
  private http = inject(HttpClient);
  private systemUrl = '/api/v1/system';
  private waUrl = '/api/v1/integrations/whatsapp';

  // --- CSV Export ---
  exportCsv(request: CsvExportRequest): Observable<Blob> {
    return this.http.post(`${this.systemUrl}/export`, request, {
      responseType: 'blob'
    });
  }

  // --- CSV Import ---
  analyzeCsv(file: File, entityType: string): Observable<CsvAnalysisResponse> {
    const formData = new FormData();
    formData.append('file', file);
    formData.append('entity_type', entityType);
    return this.http.post<CsvAnalysisResponse>(`${this.systemUrl}/import/analyze`, formData);
  }

  executeCsvImport(request: CsvImportExecutionRequest): Observable<CsvImportResult> {
    return this.http.post<CsvImportResult>(`${this.systemUrl}/import/execute`, request);
  }

  // --- Backups ---
  getBackups(): Observable<DbBackup[]> {
    return this.http.get<DbBackup[]>(`${this.systemUrl}/backups`);
  }

  generateBackup(): Observable<DbBackup> {
    return this.http.post<DbBackup>(`${this.systemUrl}/backups/generate`, {});
  }

  downloadBackup(backupId: string): Observable<Blob> {
    return this.http.get(`${this.systemUrl}/backups/${backupId}/download`, {
      responseType: 'blob'
    });
  }

  deleteBackup(backupId: string): Observable<void> {
    return this.http.delete<void>(`${this.systemUrl}/backups/${backupId}`);
  }

  // --- WhatsApp Bot & Anti-Ban Config ---
  getWhatsAppConfig(): Observable<WhatsAppConfig> {
    return this.http.get<WhatsAppConfig>(`${this.waUrl}/config`);
  }

  updateWhatsAppConfig(data: WhatsAppConfigUpdate): Observable<WhatsAppConfig> {
    return this.http.patch<WhatsAppConfig>(`${this.waUrl}/config`, data);
  }

  toggleEmergencyPause(): Observable<{ emergency_pause: boolean; message: string }> {
    return this.http.post<{ emergency_pause: boolean; message: string }>(`${this.waUrl}/emergency-pause`, {});
  }

  testSendWhatsApp(toPhone: string, message: string): Observable<{ message: string; to_phone: string }> {
    return this.http.post<{ message: string; to_phone: string }>(`${this.waUrl}/test-send`, {
      to_phone: toPhone,
      message
    });
  }

  // --- WhatsApp Templates / Respostas Rápidas ---
  getWhatsAppTemplates(category?: string, activeOnly: boolean = false): Observable<WhatsAppTemplate[]> {
    let params = new HttpParams();
    if (category) {
      params = params.set('category', category);
    }
    if (activeOnly) {
      params = params.set('active_only', 'true');
    }
    return this.http.get<WhatsAppTemplate[]>(`${this.waUrl}/templates`, { params });
  }

  createWhatsAppTemplate(data: { name: string; code: string; category: string; content: string; is_active?: boolean }): Observable<WhatsAppTemplate> {
    return this.http.post<WhatsAppTemplate>(`${this.waUrl}/templates`, data);
  }

  updateWhatsAppTemplate(id: string, data: Partial<WhatsAppTemplate>): Observable<WhatsAppTemplate> {
    return this.http.put<WhatsAppTemplate>(`${this.waUrl}/templates/${id}`, data);
  }

  deleteWhatsAppTemplate(id: string): Observable<void> {
    return this.http.delete<void>(`${this.waUrl}/templates/${id}`);
  }

  previewWhatsAppTemplate(id: string, req: { ticket_id?: string; template_content?: string; observacao?: string }): Observable<{ rendered_message: string; variables_detected: string[] }> {
    return this.http.post<{ rendered_message: string; variables_detected: string[] }>(`${this.waUrl}/templates/${id}/preview`, req);
  }

  // --- WhatsApp Outbox Fila ---
  getWhatsAppOutbox(statusFilter?: string, limit: number = 50): Observable<WhatsAppOutboxItem[]> {
    let params = new HttpParams().set('limit', limit.toString());
    if (statusFilter) {
      params = params.set('status_filter', statusFilter);
    }
    return this.http.get<WhatsAppOutboxItem[]>(`${this.waUrl}/outbox`, { params });
  }

  getWhatsAppOutboxStats(): Observable<WhatsAppOutboxStats> {
    return this.http.get<WhatsAppOutboxStats>(`${this.waUrl}/outbox/stats`);
  }

  processWhatsAppOutbox(maxBatch: number = 10): Observable<{ processed: number; failed: number; status: string; message: string }> {
    return this.http.post<{ processed: number; failed: number; status: string; message: string }>(
      `${this.waUrl}/outbox/process?max_batch=${maxBatch}`,
      {}
    );
  }

  cancelWhatsAppOutboxItem(id: string): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.waUrl}/outbox/${id}/cancel`, {});
  }

  retryWhatsAppOutboxItem(id: string): Observable<{ message: string }> {
    return this.http.post<{ message: string }>(`${this.waUrl}/outbox/${id}/retry`, {});
  }

  // --- Envio de WhatsApp vinculado a Chamado ---
  sendTicketWhatsApp(
    ticketId: string,
    req: { template_id?: string; custom_message?: string; observacao?: string; priority?: number }
  ): Observable<{ status: string; outbox_id: string; to_phone: string; message: string }> {
    return this.http.post<{ status: string; outbox_id: string; to_phone: string; message: string }>(
      `${this.waUrl}/tickets/${ticketId}/send`,
      req
    );
  }
}
