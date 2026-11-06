import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router, RouterModule } from '@angular/router';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { Ticket, TicketService } from '../ticket.service';
import { SlaBadgeComponent } from '../sla-badge/sla-badge.component';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';
import { apiErrorMessage } from '../../../core/http/api-error';

/** Filtro de SLA da lista: todos, só os que pedem atenção (atrasados, violados em aberto, em risco) ou violados. */
export type SlaFilter = 'all' | 'attention' | 'breached';

const OPEN_STATES = ['RUNNING', 'PAUSED'];

@Component({
  selector: 'app-ticket-list',
  standalone: true,
  imports: [
    CommonModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatTooltipModule,
    MatButtonToggleModule,
    RouterModule,
    LoadStateComponent,
    SlaBadgeComponent
  ],
  templateUrl: './ticket-list.component.html',
  styleUrls: ['./ticket-list.component.scss']
})
export class TicketListComponent implements OnInit {
  private ticketService = inject(TicketService);
  private router = inject(Router);
  private cdr = inject(ChangeDetectorRef);

  tickets: Ticket[] = [];
  visibleTickets: Ticket[] = [];
  slaFilter: SlaFilter = 'all';
  displayedColumns: string[] = ['title', 'requester', 'status', 'priority', 'sla', 'created_at', 'actions'];
  isLoading = false;
  loadError: string | null = null;

  /** Algum chamado da lista tem SLA? Sem nenhum, o filtro não aparece. */
  get hasSla(): boolean {
    return this.tickets.some((t) => t.sla && t.sla.state !== 'NOT_APPLICABLE');
  }

  setSlaFilter(filter: SlaFilter) {
    this.slaFilter = filter;
    this.applyFilter();
  }

  private applyFilter() {
    this.visibleTickets = this.tickets.filter((t) => {
      const s = t.sla;
      if (this.slaFilter === 'all') return true;
      if (!s || s.state === 'NOT_APPLICABLE') return false;
      const violated = s.state === 'BREACHED' || (s.breaches?.length ?? 0) > 0;
      if (this.slaFilter === 'breached') return violated || !!s.overdue;
      return OPEN_STATES.includes(s.state) && (violated || !!s.overdue || !!s.at_risk);
    });
  }

  ngOnInit() {
    this.loadTickets();
  }

  loadTickets() {
    this.isLoading = true;
    this.loadError = null;
    this.ticketService.listTickets().subscribe({
      next: (data) => {
        this.tickets = [...data];
        this.applyFilter();
        this.isLoading = false;
        this.cdr.markForCheck();
      },
      error: (err) => {
        // falha de comunicação não pode parecer "nenhum chamado"
        this.loadError = apiErrorMessage(err, 'Não foi possível carregar os chamados.');
        this.isLoading = false;
        this.cdr.markForCheck();
      }
    });
  }

  getStatusColor(status: string): 'primary' | 'accent' | 'warn' | undefined {
    switch (status) {
      case 'OPENED': return 'warn';
      case 'IN_PROGRESS': return 'accent';
      case 'PENDING': return 'primary';
      case 'RESOLVED': return 'primary';
      default: return undefined;
    }
  }

  getStatusLabel(status: string): string {
    switch (status) {
      case 'OPENED': return 'Aberto';
      case 'IN_PROGRESS': return 'Em Atendimento';
      case 'PENDING': return 'Pendente';
      case 'RESOLVED': return 'Resolvido';
      case 'CLOSED': return 'Encerrado';
      case 'CANCELED': return 'Cancelado';
      default: return status;
    }
  }

  getPriorityClass(priority: string): string {
    switch (priority) {
      case 'CRITICAL':
      case 'HIGH':
        return 'priority-high';
      case 'MEDIUM':
        return 'priority-medium';
      default:
        return 'priority-low';
    }
  }
}
