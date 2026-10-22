import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface AssetCategory {
  id: string;
  name: string;
  description?: string;
  spec_schema?: Record<string, any>;
}

export interface AssetMovement {
  id: string;
  asset_id: string;
  movement_type: string;
  from_unit_id?: string;
  to_unit_id?: string;
  from_employee_id?: string;
  to_employee_id?: string;
  status_from?: string;
  status_to?: string;
  ticket_id?: string;
  notes?: string;
  author_id: string;
  created_at: string;
}

export interface AssetUnitSimple {
  id: string;
  name: string;
  code: string;
  type?: string;
}

export interface AssetEmployeeSimple {
  id: string;
  name: string;
  registration_number: string;
  position?: string | null;
}

export interface Asset {
  id: string;
  tag: string;
  serial_number?: string | null;
  name: string;
  category_id: string;
  category?: AssetCategory;
  status: string;
  technical_specs?: Record<string, any>;
  purchase_date?: string | null;
  warranty_expires?: string | null;
  notes?: string | null;
  unit_id: string;
  employee_id?: string | null;
  unit?: AssetUnitSimple | null;
  employee?: AssetEmployeeSimple | null;
}

// --- Importação de inventário GLPI Agent (XML) ---

export type GlpiRowStatus = 'MATCHED' | 'NEW' | 'ERROR';
export type GlpiRowAction = 'update' | 'create' | 'skip';
export type GlpiRowOutcome = 'created' | 'updated' | 'skipped' | 'error';

export interface GlpiParsedInventory {
  device_id?: string | null;
  hostname?: string | null;
  chassis_type?: string | null;
  cpu_name?: string | null;
  cpu_cores?: string | null;
  cpu_threads?: string | null;
  ram_mb?: number | null;
  storage?: { model?: string; serial?: string; size_mb?: number; type?: string; interface?: string }[];
  os_name?: string | null;
  os_version?: string | null;
  os_arch?: string | null;
  bios?: { manufacturer?: string | null; model?: string | null };
  network?: { mac?: string | null; ip?: string | null; type?: string | null } | null;
  monitors?: { caption?: string; manufacturer?: string; serial?: string }[];
  software_count?: number;
  inventory_collected_at?: string | null;
  last_logged_user?: string | null;
}

export interface GlpiImportRow {
  filename: string;
  status: GlpiRowStatus;
  parsed?: GlpiParsedInventory | null;
  serial_number?: string | null;
  suggested_name?: string | null;
  matched_asset_id?: string | null;
  matched_asset_tag?: string | null;
  matched_asset_name?: string | null;
  error_message?: string | null;
}

export interface GlpiImportAnalyzeResponse {
  rows: GlpiImportRow[];
}

export interface GlpiImportDecision {
  filename: string;
  action: GlpiRowAction;
  asset_id?: string | null;
  tag?: string | null;
  name?: string | null;
  category_id?: string | null;
  unit_id?: string | null;
}

export interface GlpiImportExecuteResult {
  filename: string;
  outcome: GlpiRowOutcome;
  asset_id?: string | null;
  error_message?: string | null;
}

export interface GlpiImportExecuteResponse {
  results: GlpiImportExecuteResult[];
  created_count: number;
  updated_count: number;
  skipped_count: number;
  error_count: number;
}

@Injectable({
  providedIn: 'root'
})
export class AssetService {
  private http = inject(HttpClient);
  private assetsUrl = '/api/v1/assets';
  private movementsUrl = '/api/v1/movements';

  // Categories
  getCategories(): Observable<AssetCategory[]> {
    return this.http.get<AssetCategory[]>(`${this.assetsUrl}/categories`);
  }

  createCategory(data: Partial<AssetCategory>): Observable<AssetCategory> {
    return this.http.post<AssetCategory>(`${this.assetsUrl}/categories`, data);
  }

  updateCategory(id: string, data: Partial<AssetCategory>): Observable<AssetCategory> {
    return this.http.put<AssetCategory>(`${this.assetsUrl}/categories/${id}`, data);
  }

  deleteCategory(id: string): Observable<void> {
    return this.http.delete<void>(`${this.assetsUrl}/categories/${id}`);
  }

  // Assets
  getAssets(unitId?: string, employeeId?: string): Observable<Asset[]> {
    const params: any = {};
    if (unitId) params.unit_id = unitId;
    if (employeeId) params.employee_id = employeeId;
    return this.http.get<Asset[]>(this.assetsUrl, { params });
  }

  getAsset(id: string): Observable<Asset> {
    return this.http.get<Asset>(`${this.assetsUrl}/${id}`);
  }

  getMyAssets(): Observable<Asset[]> {
    return this.http.get<Asset[]>(`${this.assetsUrl}/me`);
  }

  getAssetTickets(assetId: string): Observable<any[]> {
    return this.http.get<any[]>(`${this.assetsUrl}/${assetId}/tickets`);
  }

  createAsset(data: any): Observable<Asset> {
    return this.http.post<Asset>(this.assetsUrl, data);
  }

  updateAsset(id: string, data: any): Observable<Asset> {
    return this.http.put<Asset>(`${this.assetsUrl}/${id}`, data);
  }

  // Movements
  getMovementsByAsset(assetId: string): Observable<AssetMovement[]> {
    return this.http.get<AssetMovement[]>(`${this.movementsUrl}/asset/${assetId}`);
  }

  createMovement(data: any): Observable<AssetMovement> {
    return this.http.post<AssetMovement>(`${this.movementsUrl}/`, data);
  }

  // Lifecycle & State Machine Operations
  reserveAsset(assetId: string, data: { employee_id?: string; ticket_id?: string; notes?: string }): Observable<AssetMovement> {
    return this.http.post<AssetMovement>(`${this.movementsUrl}/${assetId}/reserve`, data);
  }

  cancelReservation(assetId: string): Observable<AssetMovement> {
    return this.http.post<AssetMovement>(`${this.movementsUrl}/${assetId}/cancel-reservation`, {});
  }

  deliverAsset(assetId: string, data: { employee_id: string; ticket_id?: string; notes?: string }): Observable<AssetMovement> {
    return this.http.post<AssetMovement>(`${this.movementsUrl}/${assetId}/deliver`, data);
  }

  returnAsset(assetId: string, data: { ticket_id?: string; notes?: string }): Observable<AssetMovement> {
    return this.http.post<AssetMovement>(`${this.movementsUrl}/${assetId}/return`, data);
  }

  inspectAsset(assetId: string, data: { approved: boolean; send_to_maintenance?: boolean; notes?: string }): Observable<AssetMovement> {
    return this.http.post<AssetMovement>(`${this.movementsUrl}/${assetId}/inspect`, data);
  }

  // Importação de inventário GLPI Agent (XML)
  analyzeGlpiImport(files: File[]): Observable<GlpiImportAnalyzeResponse> {
    const formData = new FormData();
    files.forEach((f) => formData.append('files', f));
    return this.http.post<GlpiImportAnalyzeResponse>(`${this.assetsUrl}/glpi-import/analyze`, formData);
  }

  executeGlpiImport(files: File[], decisions: GlpiImportDecision[]): Observable<GlpiImportExecuteResponse> {
    const formData = new FormData();
    files.forEach((f) => formData.append('files', f));
    formData.append('decisions', JSON.stringify(decisions));
    return this.http.post<GlpiImportExecuteResponse>(`${this.assetsUrl}/glpi-import/execute`, formData);
  }

  // Responsibility Statement
  getResponsibilityStatementUrl(assetId: string): string {
    return `${this.assetsUrl}/${assetId}/responsibility-statement`;
  }

  openResponsibilityStatement(assetId: string): void {
    this.http.get(this.getResponsibilityStatementUrl(assetId), { responseType: 'blob' }).subscribe({
      next: (blob) => {
        const html = new Blob([blob], { type: 'text/html;charset=utf-8' });
        const url = URL.createObjectURL(html);
        window.open(url, '_blank');
        setTimeout(() => URL.revokeObjectURL(url), 60000);
      },
      error: (err) => console.error('Erro ao gerar termo de responsabilidade:', err)
    });
  }
}
