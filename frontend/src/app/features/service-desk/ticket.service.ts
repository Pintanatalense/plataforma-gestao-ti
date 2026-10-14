import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface CategoryFormField {
  id: string;
  label: string;
  type: 'text' | 'textarea' | 'number' | 'select' | 'checkbox' | 'date';
  required: boolean;
  placeholder?: string;
  help_text?: string;
  options?: string[];
}

export interface TicketCategory {
  id: string;
  name: string;
  description?: string;
  default_sector_id?: string | null;
  form_schema?: CategoryFormField[];
  is_active?: boolean;
}

export interface TicketInteraction {
  id: string;
  ticket_id: string;
  author_id: string;
  author_name?: string;
  author_email?: string;
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

export interface TicketHistoryItem {
  id: string;
  event_type: string;
  action: string;
  description: string;
  user_name?: string | null;
  user_email?: string | null;
  data?: Record<string, any>;
  created_at: string;
}

export interface Ticket {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  requester_id: string;
  requester_name?: string;
  assignee_id?: string;
  assignee_name?: string;
  category_id?: string;
  category?: TicketCategory;
  asset_ids?: string[];
  custom_fields?: Record<string, any>;
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

  createTicket(payload: {
    title: string;
    description: string;
    priority: string;
    category_id?: string;
    asset_ids?: string[];
    custom_fields?: Record<string, any>;
  }): Observable<Ticket> {
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

  createCategory(payload: {
    name: string;
    description?: string;
    default_sector_id?: string | null;
    form_schema?: CategoryFormField[];
  }): Observable<TicketCategory> {
    return this.http.post<TicketCategory>(`${this.apiUrl}/categories`, payload);
  }

  updateCategory(
    id: string,
    payload: {
      name?: string;
      description?: string;
      default_sector_id?: string | null;
      form_schema?: CategoryFormField[];
      is_active?: boolean;
    }
  ): Observable<TicketCategory> {
    return this.http.patch<TicketCategory>(`${this.apiUrl}/categories/${id}`, payload);
  }

  updateTicket(ticketId: string, payload: any): Observable<Ticket> {
    return this.http.patch<Ticket>(`${this.apiUrl}/${ticketId}`, payload);
  }

  updateTicketStatus(ticketId: string, status: string, notes?: string): Observable<Ticket> {
    return this.http.patch<Ticket>(`${this.apiUrl}/${ticketId}`, { status, notes });
  }

  getTicketHistory(ticketId: string): Observable<TicketHistoryItem[]> {
    return this.http.get<TicketHistoryItem[]>(`${this.apiUrl}/${ticketId}/history`);
  }
}
