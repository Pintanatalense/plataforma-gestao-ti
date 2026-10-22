import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatTooltipModule } from '@angular/material/tooltip';
import { Router, RouterModule } from '@angular/router';
import { Ticket, TicketService } from '../ticket.service';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';
import { apiErrorMessage } from '../../../core/http/api-error';

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
    RouterModule,
    LoadStateComponent
  ],
  templateUrl: './ticket-list.component.html',
  styleUrls: ['./ticket-list.component.scss']
})
export class TicketListComponent implements OnInit {
  private ticketService = inject(TicketService);
  private router = inject(Router);
  private cdr = inject(ChangeDetectorRef);

  tickets: Ticket[] = [];
  displayedColumns: string[] = ['title', 'requester', 'status', 'priority', 'created_at', 'actions'];
  isLoading = false;
  loadError: string | null = null;

  ngOnInit() {
    this.loadTickets();
  }

  loadTickets() {
    this.isLoading = true;
    this.loadError = null;
    this.ticketService.listTickets().subscribe({
      next: (data) => {
        this.tickets = [...data];
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
