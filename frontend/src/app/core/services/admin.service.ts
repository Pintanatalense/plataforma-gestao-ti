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
  /** Nome real do campo na API (antes o frontend lia `sha256_hash`, que não existe: a coluna mostrava sempre "N/A"). */
  checksum_sha256: string | null;
  status: 'PENDING' | 'SUCCESS' | 'FAILED';
  error_message: string | null;
  created_at: string;
  created_by_email: string | null;
  /** Pacote de anexos e logomarca (só nos backups mais recentes). */
  files_filename?: string | null;
  files_size_bytes?: number | null;
  files_count?: number | null;
}

export interface BackupVerification {
  backup_id: string;
  filename: string;
  exists: boolean;
  is_valid: boolean;
  expected_sha256?: string;
  calculated_sha256?: string;
  size_bytes?: number;
  error?: string;
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

  /** Recalcula o SHA-256 do arquivo e compara com o registrado (não prova que o backup restaura). */
  verifyBackup(backupId: string): Observable<BackupVerification> {
    return this.http.get<BackupVerification>(`${this.systemUrl}/backups/${backupId}/verify`);
  }

  generateBackup(): Observable<DbBackup> {
    return this.http.post<DbBackup>(`${this.systemUrl}/backups/generate`, {});
  }

  downloadBackup(backupId: string): Observable<Blob> {
    return this.http.get(`${this.systemUrl}/backups/${backupId}/download`, {
      responseType: 'blob'
    });
  }

  downloadBackupFiles(backupId: string): Observable<Blob> {
    return this.http.get(`${this.systemUrl}/backups/${backupId}/download-files`, {
      responseType: 'blob'
    });
  }

  deleteBackup(backupId: string): Observable<void> {
    return this.http.delete<void>(`${this.systemUrl}/backups/${backupId}`);
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

  // --- Envio de WhatsApp vinculado a Chamado ---
  sendTicketWhatsApp(
    ticketId: string,
    req: { template_id?: string; custom_message?: string; observacao?: string; priority?: number }
  ): Observable<{ status: string; delivery_id: string; message: string }> {
    return this.http.post<{ status: string; delivery_id: string; message: string }>(
      `${this.waUrl}/tickets/${ticketId}/send`,
      req
    );
  }

  // --- Gestão de Ambientes & Demonstração (MOD-01) ---
  getDemoStatus(): Observable<DemoStatus> {
    return this.http.get<DemoStatus>('/api/v1/system/demo/status');
  }

  previewDemoClean(): Observable<DemoCleanPreview> {
    return this.http.get<DemoCleanPreview>('/api/v1/system/demo/preview-clean');
  }

  cleanDemoData(confirmationPhrase: string): Observable<{ status: string; message: string; summary: any }> {
    return this.http.post<{ status: string; message: string; summary: any }>('/api/v1/system/demo/clean', {
      confirmation_phrase: confirmationPhrase
    });
  }

  resetAllData(confirmationPhrase: string): Observable<ResetAllResult> {
    return this.http.post<ResetAllResult>('/api/v1/system/demo/reset-all', {
      confirmation_phrase: confirmationPhrase
    });
  }

  seedDemoData(): Observable<{ status: string; message: string }> {
    return this.http.post<{ status: string; message: string }>('/api/v1/system/demo/seed', {});
  }

  seedTestData(): Observable<{ status: string; message: string; summary?: any }> {
    return this.http.post<{ status: string; message: string; summary?: any }>('/api/v1/system/demo/seed-test', {});
  }

  // --- Notificações por E-mail & Servidor SMTP (MOD-11) ---
  getSmtpConfig(): Observable<SmtpConfig> {
    return this.http.get<SmtpConfig>('/api/v1/notifications/email/config');
  }

  updateSmtpConfig(config: SmtpConfig): Observable<SmtpConfig> {
    return this.http.put<SmtpConfig>('/api/v1/notifications/email/config', config);
  }

  getPasswordResetConfig(): Observable<PasswordResetConfig> {
    return this.http.get<PasswordResetConfig>('/api/v1/notifications/email/password-reset');
  }

  setPasswordReset(enabled: boolean): Observable<PasswordResetConfig> {
    return this.http.put<PasswordResetConfig>('/api/v1/notifications/email/password-reset', { enabled });
  }

  testSmtpConnection(req: { target_email: string } & Partial<SmtpConfig>): Observable<{ success: boolean; message: string; target_email: string }> {
    return this.http.post<{ success: boolean; message: string; target_email: string }>('/api/v1/notifications/email/test', req);
  }
}

export interface DemoStatus {
  system_mode: 'DEMO' | 'PRODUCTION';
  is_demo_mode: boolean;
  total_demo_records: number;
  demo_records_count: Record<string, number>;
  has_recent_valid_backup: boolean;
  latest_backup: {
    filename: string;
    created_at: string;
    size_bytes: number;
    is_usable: boolean;
  } | null;
}

export interface DemoCleanPreview {
  demo_records: Record<string, number>;
  total_to_remove: number;
  has_valid_backup: boolean;
  required_confirmation_phrase: string;
  preserved_elements: string[];
}

export interface ResetAllResult {
  success: boolean;
  message: string;
  summary: Record<string, number | string | null>;
}

export interface PasswordResetConfig {
  enabled: boolean;
  smtp_ready: boolean;
}

export interface SmtpConfig {
  is_enabled: boolean;
  host: string;
  port: number;
  security: string;
  username: string;
  password?: string;
  from_email: string;
  from_name: string;
  app_base_url: string;
}
