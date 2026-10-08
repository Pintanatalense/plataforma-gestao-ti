import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { Router, RouterModule } from '@angular/router';
import { Ticket, TicketService } from '../ticket.service';

@Component({
  selector: 'app-ticket-list',
  standalone: true,
  imports: [CommonModule, MatTableModule, MatButtonModule, MatIconModule, MatChipsModule, RouterModule],
  templateUrl: './ticket-list.component.html',
  styleUrls: ['./ticket-list.component.scss']
})
export class TicketListComponent implements OnInit {
  private ticketService = inject(TicketService);
  private router = inject(Router);

  tickets: Ticket[] = [];
  displayedColumns: string[] = ['title', 'status', 'priority', 'created_at', 'actions'];

  ngOnInit() {
    this.loadTickets();
  }

  loadTickets() {
    this.ticketService.listTickets().subscribe({
      next: (data) => this.tickets = data,
      error: (err) => console.error(err)
    });
  }

  getStatusColor(status: string): string {
    switch (status) {
      case 'OPENED': return 'warn';
      case 'IN_PROGRESS': return 'accent';
      case 'PENDING': return 'primary';
      case 'RESOLVED': return 'primary'; // Or custom classes later
      case 'CLOSED': return 'default';
      default: return 'default';
    }
  }
}
