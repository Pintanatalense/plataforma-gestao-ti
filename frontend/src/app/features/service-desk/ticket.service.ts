import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface TicketCategory {
  id: string;
  name: string;
  description?: string;
  default_sector_id?: string | null;
}

export interface TicketInteraction {
  id: string;
  ticket_id: string;
  author_id: string;
  message: string;
  is_internal: boolean;
  created_at: string;
}

export interface TicketMaterial {
  id: string;
  ticket_id: string;
  stock_item_id: string;
  quantity: number;
  author_id: string;
  created_at: string;
}

export interface Ticket {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  requester_id: string;
  assignee_id?: string;
  category_id?: string;
  asset_ids?: string[];
  created_at: string;
  updated_at: string;
  interactions: TicketInteraction[];
  materials?: TicketMaterial[];
}

@Injectable({
  providedIn: 'root'
})
export class TicketService {
  private http = inject(HttpClient);
  private apiUrl = '/api/v1/tickets';

  listTickets(): Observable<Ticket[]> {
    return this.http.get<Ticket[]>(this.apiUrl);
  }

  getTicket(id: string): Observable<Ticket> {
    return this.http.get<Ticket>(`${this.apiUrl}/${id}`);
  }

  createTicket(payload: { title: string; description: string; priority: string; category_id?: string; asset_ids?: string[] }): Observable<Ticket> {
    return this.http.post<Ticket>(this.apiUrl, payload);
  }

  addInteraction(ticketId: string, message: string, is_internal: boolean): Observable<TicketInteraction> {
    return this.http.post<TicketInteraction>(`${this.apiUrl}/${ticketId}/interactions`, {
      message,
      is_internal
    });
  }

  addMaterial(ticketId: string, payload: { stock_item_id: string; quantity: number }): Observable<TicketMaterial> {
    return this.http.post<TicketMaterial>(`${this.apiUrl}/${ticketId}/materials`, payload);
  }

  getCategories(): Observable<TicketCategory[]> {
    return this.http.get<TicketCategory[]>(`${this.apiUrl}/categories`);
  }

  createCategory(payload: { name: string; description?: string; default_sector_id?: string | null }): Observable<TicketCategory> {
    return this.http.post<TicketCategory>(`${this.apiUrl}/categories`, payload);
  }

  updateCategory(id: string, payload: { name?: string; description?: string; default_sector_id?: string | null }): Observable<TicketCategory> {
    return this.http.patch<TicketCategory>(`${this.apiUrl}/categories/${id}`, payload);
  }

  updateTicket(ticketId: string, payload: any): Observable<Ticket> {
    return this.http.patch<Ticket>(`${this.apiUrl}/${ticketId}`, payload);
  }
}
