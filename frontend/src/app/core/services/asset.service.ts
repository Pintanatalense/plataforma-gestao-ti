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
  notes?: string;
  author_id: string;
  created_at: string;
}

export interface Asset {
  id: string;
  tag: string;
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

  // Assets
  getAssets(unitId?: string, employeeId?: string): Observable<Asset[]> {
    let params: any = {};
    if (unitId) params.unit_id = unitId;
    if (employeeId) params.employee_id = employeeId;
    return this.http.get<Asset[]>(this.assetsUrl, { params });
  }

  getAsset(id: string): Observable<Asset> {
    return this.http.get<Asset>(`${this.assetsUrl}/${id}`);
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
}
