import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface InventoryAuditItem {
  id: string;
  audit_id: string;
  item_type: 'ASSET' | 'STOCK';
  asset_id?: string | null;
  stock_item_id?: string | null;
  item_name?: string | null;
  item_code?: string | null;
  expected_status?: string | null;
  expected_quantity?: number | null;
  actual_status?: string | null;
  actual_quantity?: number | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
}

export interface InventoryAudit {
  id: string;
  name: string;
  unit_id: string;
  unit_name?: string | null;
  auditor_id: string;
  auditor_name?: string | null;
  status: 'OPENED' | 'IN_PROGRESS' | 'CLOSED' | 'CANCELLED';
  start_date?: string | null;
  end_date?: string | null;
  notes?: string | null;
  created_at: string;
  updated_at: string;
  items?: InventoryAuditItem[];
}

@Injectable({
  providedIn: 'root'
})
export class InventoryService {
  private http = inject(HttpClient);
  private apiUrl = '/api/v1/inventory';

  listAudits(unitId?: string): Observable<InventoryAudit[]> {
    const params: any = {};
    if (unitId) params.unit_id = unitId;
    return this.http.get<InventoryAudit[]>(this.apiUrl, { params });
  }

  getAudit(id: string): Observable<InventoryAudit> {
    return this.http.get<InventoryAudit>(`${this.apiUrl}/${id}`);
  }

  createAudit(data: { name: string; unit_id: string; auditor_id: string }): Observable<InventoryAudit> {
    return this.http.post<InventoryAudit>(this.apiUrl, data);
  }

  populateItems(auditId: string): Observable<InventoryAudit> {
    return this.http.post<InventoryAudit>(`${this.apiUrl}/${auditId}/populate`, {});
  }

  updateAudit(id: string, data: Partial<InventoryAudit>): Observable<InventoryAudit> {
    return this.http.patch<InventoryAudit>(`${this.apiUrl}/${id}`, data);
  }

  addItem(auditId: string, item: Partial<InventoryAuditItem>): Observable<InventoryAuditItem> {
    return this.http.post<InventoryAuditItem>(`${this.apiUrl}/${auditId}/items`, item);
  }

  updateItem(auditId: string, itemId: string, item: Partial<InventoryAuditItem>): Observable<InventoryAuditItem> {
    return this.http.patch<InventoryAuditItem>(`${this.apiUrl}/${auditId}/items/${itemId}`, item);
  }
}
