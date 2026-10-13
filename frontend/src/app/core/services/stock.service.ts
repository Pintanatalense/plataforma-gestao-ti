import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface StockItem {
  id: string;
  name: string;
  description?: string;
  unit_id: string;
  quantity: number;
  min_quantity: number;
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

  getItems(unitId?: string): Observable<StockItem[]> {
    let params: any = {};
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
  }): Observable<StockItem> {
    return this.http.post<StockItem>(`${this.apiUrl}/items`, data);
  }

  updateItem(id: string, data: Partial<StockItem>): Observable<StockItem> {
    return this.http.put<StockItem>(`${this.apiUrl}/items/${id}`, data);
  }

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
