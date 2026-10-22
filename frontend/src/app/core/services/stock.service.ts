import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface StockCategory {
  id: string;
  name: string;
  description?: string;
  spec_schema?: Record<string, any>;
  created_at?: string;
  updated_at?: string;
}

export interface StockItem {
  id: string;
  name: string;
  description?: string;
  unit_id: string;
  quantity: number;
  min_quantity: number;
  category_id?: string | null;
  technical_specs?: Record<string, any>;
  category?: StockCategory;
  created_at: string;
  updated_at: string;
  unitName?: string;
}

export interface StockMovement {
  id: string;
  item_id: string;
  movement_type: string;
  quantity: number;
  notes?: string;
  author_id: string;
  created_at: string;
  updated_at: string;
}

@Injectable({
  providedIn: 'root'
})
export class StockService {
  private http = inject(HttpClient);
  private apiUrl = '/api/v1/stock';

  // --- Categories ---
  getCategories(): Observable<StockCategory[]> {
    return this.http.get<StockCategory[]>(`${this.apiUrl}/categories`);
  }

  getCategory(id: string): Observable<StockCategory> {
    return this.http.get<StockCategory>(`${this.apiUrl}/categories/${id}`);
  }

  createCategory(data: Partial<StockCategory>): Observable<StockCategory> {
    return this.http.post<StockCategory>(`${this.apiUrl}/categories`, data);
  }

  updateCategory(id: string, data: Partial<StockCategory>): Observable<StockCategory> {
    return this.http.put<StockCategory>(`${this.apiUrl}/categories/${id}`, data);
  }

  deleteCategory(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/categories/${id}`);
  }

  // --- Items ---
  getItems(unitId?: string): Observable<StockItem[]> {
    const params: any = {};
    if (unitId) params.unit_id = unitId;
    return this.http.get<StockItem[]>(`${this.apiUrl}/items`, { params });
  }

  getItem(id: string): Observable<StockItem> {
    return this.http.get<StockItem>(`${this.apiUrl}/items/${id}`);
  }

  createItem(data: {
    name: string;
    description?: string;
    unit_id: string;
    initial_quantity?: number;
    min_quantity?: number;
    category_id?: string | null;
    technical_specs?: Record<string, any>;
  }): Observable<StockItem> {
    return this.http.post<StockItem>(`${this.apiUrl}/items`, data);
  }

  updateItem(id: string, data: Partial<StockItem>): Observable<StockItem> {
    return this.http.put<StockItem>(`${this.apiUrl}/items/${id}`, data);
  }

  // --- Movements ---
  listMovements(itemId: string): Observable<StockMovement[]> {
    return this.http.get<StockMovement[]>(`${this.apiUrl}/movements/item/${itemId}`);
  }

  addMovement(data: {
    item_id: string;
    movement_type: string;
    quantity: number;
    notes?: string;
  }): Observable<StockMovement> {
    return this.http.post<StockMovement>(`${this.apiUrl}/movements`, data);
  }
}
