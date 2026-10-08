import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

export interface TicketCategory {
  id: string;
  name: string;
  description?: string;
}

export interface TicketInteraction {
  id: string;
  ticket_id: string;
  author_id: string;
  message: string;
  is_internal: boolean;
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
  created_at: string;
  updated_at: string;
  interactions: TicketInteraction[];
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

  createTicket(payload: {title: string, description: string, priority: string, category_id?: string}): Observable<Ticket> {
    return this.http.post<Ticket>(this.apiUrl, payload);
  }

  addInteraction(ticketId: string, message: string, is_internal: boolean): Observable<TicketInteraction> {
    return this.http.post<TicketInteraction>(`${this.apiUrl}/${ticketId}/interactions`, {
      message,
      is_internal
    });
  }

  getCategories(): Observable<TicketCategory[]> {
    return this.http.get<TicketCategory[]>(`${this.apiUrl}/categories`);
  }

  updateTicket(ticketId: string, payload: any): Observable<Ticket> {
    return this.http.patch<Ticket>(`${this.apiUrl}/${ticketId}`, payload);
  }
}
