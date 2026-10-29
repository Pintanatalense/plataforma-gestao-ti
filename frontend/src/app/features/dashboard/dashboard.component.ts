import { Component, OnInit, inject, ChangeDetectorRef } from '@angular/core';
import { PT_BR } from '../../core/i18n/pt-br';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatCardModule } from '@angular/material/card';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatChipsModule } from '@angular/material/chips';
import { MatTableModule } from '@angular/material/table';
import { MatTooltipModule } from '@angular/material/tooltip';

import { AuthService, UserAccount } from '../../core/auth/auth.service';
import { apiErrorMessage } from '../../core/http/api-error';
import { Ticket, TicketService } from '../service-desk/ticket.service';
import { Asset, AssetService } from '../../core/services/asset.service';
import { StockItem, StockService } from '../../core/services/stock.service';
import { InventoryAudit, InventoryService } from '../../core/services/inventory.service';

type DashboardSource = 'tickets' | 'assets' | 'stock' | 'audits';
type SourceState = 'loading' | 'ok' | 'error';

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
  private cdr = inject(ChangeDetectorRef);

  today = new Date();
  readonly ptBr = PT_BR;

  /**
   * Estado de cada fonte de dados. Uma fonte que falhou NÃO vira zero: o cartão mostra "—" e o painel avisa
   * (antes, `error: () => {}` fazia uma falha aparecer como "0 chamados" e "Estoque Regular").
   */
  state: Record<DashboardSource, SourceState> = { tickets: 'loading', assets: 'ok', stock: 'ok', audits: 'ok' };
  readonly sourceLabels: Record<DashboardSource, string> = {
    tickets: 'chamados',
    assets: 'ativos',
    stock: 'estoque',
    audits: 'inventário'
  };
  loadError = '';
  /** Número da carga em andamento: respostas de uma carga anterior (mais lentas) são descartadas. */
  private loadSeq = 0;

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
    const seq = ++this.loadSeq;
    const live = () => seq === this.loadSeq;
    this.loadError = '';
    this.state = {
      tickets: 'loading',
      assets: this.authService.hasPermission('assets.read') ? 'loading' : 'ok',
      stock: this.authService.hasPermission('stock.read') ? 'loading' : 'ok',
      audits: this.authService.hasPermission('inventory.read') ? 'loading' : 'ok'
    };

    // Tickets
    this.ticketService.listTickets().subscribe({
      next: (tickets) => {
        if (!live()) return;
        this.totalTickets = tickets.length;
        this.openedTickets = tickets.filter((t) => t.status === 'OPENED').length;
        this.inProgressTickets = tickets.filter((t) => t.status === 'IN_PROGRESS').length;
        this.recentTickets = [...tickets.slice(0, 5)];
        this.finish('tickets', 'ok');
      },
      error: (err) => live() && this.fail('tickets', err)
    });

    // Assets
    if (this.authService.hasPermission('assets.read')) {
      this.assetService.getAssets().subscribe({
        next: (assets) => {
          if (!live()) return;
          this.totalAssets = assets.length;
          this.assetsInUse = assets.filter((a) => a.status === 'IN_USE').length;
          this.assetsInStock = assets.filter((a) => a.status === 'IN_STOCK').length;
          this.finish('assets', 'ok');
        },
        error: (err) => live() && this.fail('assets', err)
      });
    }

    // Stock
    if (this.authService.hasPermission('stock.read')) {
      this.stockService.getItems().subscribe({
        next: (items) => {
          if (!live()) return;
          this.totalStockItems = items.length;
          this.lowStockList = items.filter((i) => i.quantity <= i.min_quantity);
          this.lowStockItemsCount = this.lowStockList.length;
          this.finish('stock', 'ok');
        },
        error: (err) => live() && this.fail('stock', err)
      });
    }

    // Inventory Audits
    if (this.authService.hasPermission('inventory.read')) {
      this.inventoryService.listAudits().subscribe({
        next: (audits) => {
          if (!live()) return;
          this.activeAuditsCount = audits.filter(
            (a) => a.status === 'OPENED' || a.status === 'IN_PROGRESS'
          ).length;
          this.finish('audits', 'ok');
        },
        error: (err) => live() && this.fail('audits', err)
      });
    }
  }

  private finish(source: DashboardSource, result: SourceState): void {
    this.state = { ...this.state, [source]: result };
    this.cdr.markForCheck();
  }

  private fail(source: DashboardSource, err: unknown): void {
    this.loadError = apiErrorMessage(err, 'Não foi possível carregar os dados.');
    this.finish(source, 'error');
  }

  /** Fontes que falharam (para o aviso do topo). */
  get failedSources(): DashboardSource[] {
    return (Object.keys(this.state) as DashboardSource[]).filter((s) => this.state[s] === 'error');
  }

  get failedLabels(): string {
    return this.failedSources.map((s) => this.sourceLabels[s]).join(', ');
  }

  /** Valor para exibir: o número só quando a fonte carregou; "…" enquanto carrega; "—" se falhou. */
  show(source: DashboardSource, value: number): string | number {
    return this.state[source] === 'ok' ? value : this.state[source] === 'loading' ? '…' : '—';
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
