import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
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
  id: string;
  is_active: boolean;
  provider: 'MOCK' | 'EVOLUTION_API' | 'META_CLOUD';
  base_url: string | null;
  api_key_configured: boolean;
  instance_name: string | null;
  webhook_secret_configured: boolean;
  updated_at: string | null;
}

export interface WhatsAppConfigUpdate {
  is_active?: boolean;
  provider?: 'MOCK' | 'EVOLUTION_API' | 'META_CLOUD';
  base_url?: string;
  api_key?: string;
  instance_name?: string;
  webhook_secret?: string;
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

  // --- WhatsApp Bot ---
  getWhatsAppConfig(): Observable<WhatsAppConfig> {
    return this.http.get<WhatsAppConfig>(`${this.waUrl}/config`);
  }

  updateWhatsAppConfig(data: WhatsAppConfigUpdate): Observable<WhatsAppConfig> {
    return this.http.patch<WhatsAppConfig>(`${this.waUrl}/config`, data);
  }

  testSendWhatsApp(toPhone: string, message: string): Observable<{ status: string; detail: string }> {
    return this.http.post<{ status: string; detail: string }>(`${this.waUrl}/test-send`, {
      to_phone: toPhone,
      message
    });
  }
}
