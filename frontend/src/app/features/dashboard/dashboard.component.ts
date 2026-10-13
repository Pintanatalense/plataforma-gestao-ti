import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AuthService, UserAccount } from '../../core/auth/auth.service';
import { Ticket, TicketService } from '../service-desk/ticket.service';
import { Asset, AssetService } from '../../core/services/asset.service';
import { StockItem, StockService } from '../../core/services/stock.service';
import { InventoryAudit, InventoryService } from '../../core/services/inventory.service';

@Component({
  selector: 'app-dashboard',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatCardModule,
    MatButtonModule,
    MatIconModule,
    MatChipsModule,
    MatTableModule,
    MatTooltipModule
  ],
  templateUrl: './dashboard.component.html',
  styleUrls: ['./dashboard.component.scss']
})
export class Dashboard implements OnInit {
  authService = inject(AuthService);
  private ticketService = inject(TicketService);
  private assetService = inject(AssetService);
  private stockService = inject(StockService);
  private inventoryService = inject(InventoryService);

  today = new Date();

  // Metrics
  totalTickets = 0;
  openedTickets = 0;
  inProgressTickets = 0;
  totalAssets = 0;
  assetsInUse = 0;
  assetsInStock = 0;
  totalStockItems = 0;
  lowStockItemsCount = 0;
  activeAuditsCount = 0;

  recentTickets: Ticket[] = [];
  lowStockList: StockItem[] = [];
  ticketColumns = ['title', 'status', 'priority', 'created_at', 'actions'];

  ngOnInit(): void {
    this.loadMetrics();
  }

  loadMetrics(): void {
    // Tickets
    this.ticketService.listTickets().subscribe({
      next: (tickets) => {
        this.totalTickets = tickets.length;
        this.openedTickets = tickets.filter((t) => t.status === 'OPENED').length;
        this.inProgressTickets = tickets.filter((t) => t.status === 'IN_PROGRESS').length;
        this.recentTickets = tickets.slice(0, 5);
      },
      error: () => {}
    });

    // Assets
    this.assetService.getAssets().subscribe({
      next: (assets) => {
        this.totalAssets = assets.length;
        this.assetsInUse = assets.filter((a) => a.status === 'IN_USE').length;
        this.assetsInStock = assets.filter((a) => a.status === 'IN_STOCK').length;
      },
      error: () => {}
    });

    // Stock
    this.stockService.getItems().subscribe({
      next: (items) => {
        this.totalStockItems = items.length;
        this.lowStockList = items.filter((i) => i.quantity <= i.min_quantity);
        this.lowStockItemsCount = this.lowStockList.length;
      },
      error: () => {}
    });

    // Inventory Audits
    this.inventoryService.listAudits().subscribe({
      next: (audits) => {
        this.activeAuditsCount = audits.filter(
          (a) => a.status === 'OPENED' || a.status === 'IN_PROGRESS'
        ).length;
      },
      error: () => {}
    });
  }

  getTicketStatusClass(status: string): string {
    switch (status) {
      case 'OPENED':
        return 'chip-opened';
      case 'IN_PROGRESS':
        return 'chip-progress';
      case 'RESOLVED':
        return 'chip-resolved';
      case 'CLOSED':
        return 'chip-closed';
      default:
        return 'chip-default';
    }
  }

  getTicketStatusLabel(status: string): string {
    switch (status) {
      case 'OPENED':
        return 'Aberto';
      case 'IN_PROGRESS':
        return 'Em Atendimento';
      case 'RESOLVED':
        return 'Resolvido';
      case 'CLOSED':
        return 'Encerrado';
      default:
        return status;
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
