import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

import { SlaInfo } from './sla.service';

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
  /** Nulo = "Não se aplica" (sem relógio de SLA). */
  sla_policy_id?: string | null;
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

export interface TicketAssetBrief {
  id: string;
  tag: string;
  name: string;
  status: string;
  unit_id: string;
  employee_id?: string | null;
}

export interface Ticket {
  id: string;
  title: string;
  description: string;
  status: string;
  priority: string;
  requester_id: string;
  requester_name?: string;
  requester_phone?: string;
  assignee_id?: string;

  assignee_name?: string;
  category_id?: string;
  category?: TicketCategory;
  asset_ids?: string[];
  assets?: TicketAssetBrief[];
  custom_fields?: Record<string, any>;
  created_at: string;
  updated_at: string;
  interactions: TicketInteraction[];
  materials?: TicketMaterial[];
  sla?: SlaInfo;
  created_by_user_id?: string | null;
  created_by_name?: string | null;
  // Chamados vinculados (ADR-026). `parent_ticket_id` só vem para quem pode ver o principal.
  parent_ticket_id?: string | null;
  is_required?: boolean;
  replaces_ticket_id?: string | null;
  template_id?: string | null;
  children_progress?: ChildrenProgress | null;
}

export interface ChildrenProgress {
  total: number;
  done: number;
  canceled: number;
  required_pending: number;
  overdue: number;
  steps_overdue: number;
  process_overdue: boolean;
}

export interface ChildTicketSummary {
  id: string;
  title: string;
  status: string;
  is_required: boolean;
  responsible_sector_id: string;
  responsible_sector_name?: string | null;
  category_id?: string | null;
  category_name?: string | null;
  assignee_name?: string | null;
  created_at: string;
  replaces_ticket_id?: string | null;
  replaced_by_ticket_id?: string | null;
  resolution_due_at?: string | null;
  overdue: boolean;
  at_risk: boolean;
}

export interface ChildrenOverview {
  progress: ChildrenProgress;
  children: ChildTicketSummary[];
}

/** Um subchamado a criar: passa pelas mesmas regras de um chamado comum no backend. */
export interface ChildTicketSpec {
  category_id: string;
  title: string;
  description: string;
  is_required: boolean;
  responsible_sector_id?: string | null;
  custom_fields?: Record<string, any>;
  priority?: string | null;
}

export interface TicketTemplateItem {
  id?: string;
  category_id: string;
  responsible_sector_id?: string | null;
  title: string;
  description: string;
  default_custom_fields?: Record<string, any>;
  is_required: boolean;
  sort?: number;
}

export interface TicketTemplate {
  id: string;
  name: string;
  description?: string | null;
  is_active: boolean;
  items: TicketTemplateItem[];
}

export const STATUS_LABELS: Record<string, string> = {
  OPENED: 'Aberto',
  IN_PROGRESS: 'Em Atendimento',
  PENDING: 'Pendente',
  RESOLVED: 'Resolvido',
  CLOSED: 'Encerrado',
  CANCELED: 'Cancelado'
};

/** Uma chave por intenção de envio: repetir o mesmo pedido não duplica chamados (ADR-026). */
export function newIdempotencyKey(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID();
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
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

  createTicket(
    payload: {
      title: string;
      description: string;
      priority: string;
      category_id?: string;
      asset_ids?: string[];
      custom_fields?: Record<string, any>;
      requester_id?: string | null;
      template_id?: string | null;
      children?: ChildTicketSpec[];
    },
    idempotencyKey?: string
  ): Observable<Ticket> {
    return this.http.post<Ticket>(this.apiUrl, payload, { headers: this.keyHeader(idempotencyKey) });
  }

  private keyHeader(key?: string): Record<string, string> {
    return key ? { 'Idempotency-Key': key } : {};
  }

  // --- Chamados vinculados (ADR-026) ---------------------------------------------------------------------

  getChildren(parentId: string): Observable<ChildrenOverview> {
    return this.http.get<ChildrenOverview>(`${this.apiUrl}/${parentId}/children`);
  }

  addChildren(parentId: string, children: ChildTicketSpec[], idempotencyKey?: string): Observable<Ticket[]> {
    return this.http.post<Ticket[]>(
      `${this.apiUrl}/${parentId}/children`, { children }, { headers: this.keyHeader(idempotencyKey) }
    );
  }

  cancelChild(childId: string, reason: string): Observable<Ticket> {
    return this.http.post<Ticket>(`${this.apiUrl}/${childId}/cancel`, { reason });
  }

  replaceChild(childId: string, reason: string, child: ChildTicketSpec): Observable<Ticket> {
    return this.http.post<Ticket>(`${this.apiUrl}/${childId}/replace`, { reason, child });
  }

  setChildRequirement(childId: string, isRequired: boolean, reason: string): Observable<Ticket> {
    return this.http.patch<Ticket>(`${this.apiUrl}/${childId}/requirement`, { is_required: isRequired, reason });
  }

  // --- Modelos de atendimento ----------------------------------------------------------------------------

  listTemplates(includeInactive = false): Observable<TicketTemplate[]> {
    const query = includeInactive ? '?include_inactive=true' : '';
    return this.http.get<TicketTemplate[]>(`/api/v1/ticket-templates${query}`);
  }

  createTemplate(payload: Omit<TicketTemplate, 'id'>): Observable<TicketTemplate> {
    return this.http.post<TicketTemplate>('/api/v1/ticket-templates', payload);
  }

  updateTemplate(id: string, payload: Omit<TicketTemplate, 'id'>): Observable<TicketTemplate> {
    return this.http.put<TicketTemplate>(`/api/v1/ticket-templates/${id}`, payload);
  }

  deactivateTemplate(id: string): Observable<void> {
    return this.http.delete<void>(`/api/v1/ticket-templates/${id}`);
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
    sla_policy_id?: string | null;
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
      sla_policy_id?: string | null;
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

  // Ticket Assets Lifecycle
  linkAssetToTicket(ticketId: string, assetId: string): Observable<any> {
    return this.http.post(`${this.apiUrl}/${ticketId}/assets/${assetId}`, {});
  }

  unlinkAssetFromTicket(ticketId: string, assetId: string): Observable<any> {
    return this.http.delete(`${this.apiUrl}/${ticketId}/assets/${assetId}`);
  }

  reserveTicketAsset(
    ticketId: string,
    assetId: string,
    payload?: { employee_id?: string; notes?: string }
  ): Observable<any> {
    return this.http.post(`${this.apiUrl}/${ticketId}/assets/${assetId}/reserve`, payload || {});
  }

  deliverTicketAsset(
    ticketId: string,
    assetId: string,
    payload?: { employee_id?: string; notes?: string }
  ): Observable<any> {
    return this.http.post(`${this.apiUrl}/${ticketId}/assets/${assetId}/deliver`, payload || {});
  }

  returnTicketAsset(
    ticketId: string,
    assetId: string,
    payload?: { notes?: string }
  ): Observable<any> {
    return this.http.post(`${this.apiUrl}/${ticketId}/assets/${assetId}/return`, payload || {});
  }

  inspectTicketAsset(
    ticketId: string,
    assetId: string,
    payload: {
      approved: boolean;
      notes?: string;
      send_to_maintenance?: boolean;
    }
  ): Observable<any> {
    return this.http.post(`${this.apiUrl}/${ticketId}/assets/${assetId}/inspect`, payload);
  }
}
