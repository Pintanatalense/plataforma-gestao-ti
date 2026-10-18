import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatInputModule } from '@angular/material/input';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import {
  DeliveryDetail,
  DeliveryFilters,
  DeliveryItem,
  NotificationsAdminService
} from '../../../core/services/notifications-admin.service';

const PAGE_SIZE = 25;

export const STATUS_LABELS: Record<string, string> = {
  PENDING: 'Pendente',
  SENDING: 'Enviando',
  SENT: 'Enviada',
  DEAD: 'Falhou (definitivo)',
  SKIPPED: 'Ignorada',
  CANCELLED: 'Cancelada'
};

@Component({
  selector: 'app-deliveries',
  standalone: true,
  imports: [
    CommonModule, FormsModule, DatePipe,
    MatButtonModule, MatIconModule, MatFormFieldModule, MatSelectModule, MatInputModule, MatSnackBarModule
  ],
  template: `
    <section class="filters">
      <mat-form-field appearance="outline">
        <mat-label>Canal</mat-label>
        <mat-select [(ngModel)]="filters.channel" (selectionChange)="search()" data-testid="f-channel">
          <mat-option value="">Todos</mat-option>
          <mat-option value="in_app">Caixa de entrada</mat-option>
          <mat-option value="email">E-mail</mat-option>
        </mat-select>
      </mat-form-field>
      <mat-form-field appearance="outline">
        <mat-label>Situação</mat-label>
        <mat-select [(ngModel)]="filters.status" (selectionChange)="search()" data-testid="f-status">
          <mat-option value="">Todas</mat-option>
          @for (s of statuses; track s) {
            <mat-option [value]="s">{{ label(s) }}</mat-option>
          }
        </mat-select>
      </mat-form-field>
      <mat-form-field appearance="outline">
        <mat-label>Destinatário (e-mail)</mat-label>
        <input matInput [(ngModel)]="filters.recipient" (keyup.enter)="search()" />
      </mat-form-field>
      <mat-form-field appearance="outline">
        <mat-label>De</mat-label>
        <input matInput type="date" [(ngModel)]="filters.date_from" (change)="search()" />
      </mat-form-field>
      <mat-form-field appearance="outline">
        <mat-label>Até</mat-label>
        <input matInput type="date" [(ngModel)]="filters.date_to" (change)="search()" />
      </mat-form-field>
      <button mat-stroked-button (click)="search()"><mat-icon>refresh</mat-icon> Atualizar</button>
    </section>

    @if (error()) {
      <p class="error" role="alert">{{ error() }}</p>
    }

    <div class="table-wrap">
      <table class="grid" data-testid="deliveries-table">
        <thead>
          <tr><th>Quando</th><th>Evento</th><th>Destinatário</th><th>Canal</th><th>Situação</th><th>Tent.</th><th></th></tr>
        </thead>
        <tbody>
          @for (d of items(); track d.id) {
            <tr [class.selected]="detail()?.id === d.id" (click)="open(d)" data-testid="delivery-row">
              <td>{{ d.created_at | date: 'dd/MM HH:mm' }}</td>
              <td>{{ d.event_type }}</td>
              <td>{{ d.recipient_email || d.address }}</td>
              <td>{{ d.channel }}</td>
              <td><span class="chip" [class]="'s-' + d.status.toLowerCase()">{{ label(d.status) }}</span></td>
              <td>{{ d.attempts }}/{{ d.max_attempts }}</td>
              <td class="row-actions">
                @if (d.status === 'DEAD') {
                  <button mat-button (click)="resend(d, $event)" data-testid="resend">Reenviar</button>
                }
                @if (d.status === 'PENDING') {
                  <button mat-button (click)="cancel(d, $event)" data-testid="cancel">Cancelar</button>
                }
              </td>
            </tr>
          } @empty {
            <tr><td colspan="7" class="empty">Nenhuma entrega encontrada.</td></tr>
          }
        </tbody>
      </table>
    </div>

    <div class="pager">
      <span>{{ total() }} entrega(s)</span>
      <button mat-button (click)="page(-1)" [disabled]="offset() === 0">Anterior</button>
      <button mat-button (click)="page(1)" [disabled]="offset() + items().length >= total()">Próxima</button>
    </div>

    @if (detail(); as d) {
      <section class="detail" data-testid="delivery-detail">
        <h3>{{ d.title }}</h3>
        <p><strong>Para:</strong> {{ d.recipient_email || d.address }} · <strong>Canal:</strong> {{ d.channel }} ·
          <strong>Prioridade:</strong> {{ d.priority }}</p>
        @if (d.last_error) {
          <p class="error"><strong>Último erro:</strong> {{ d.last_error }}</p>
        }
        <h4>Tentativas</h4>
        <ul>
          @for (a of d.attempt_log; track a.attempt_no) {
            <li>#{{ a.attempt_no }} — {{ a.outcome }} — {{ a.started_at | date: 'dd/MM HH:mm:ss' }}{{ a.error ? ' — ' + a.error : '' }}</li>
          } @empty {
            <li>Nenhuma tentativa ainda.</li>
          }
        </ul>
        <details>
          <summary>Dados do evento</summary>
          <pre>{{ d.event_payload | json }}</pre>
        </details>
      </section>
    }
  `,
  styles: [`
    .filters { display: flex; flex-wrap: wrap; gap: 12px; align-items: baseline; margin-top: 16px; }
    .filters mat-form-field { flex: 1 1 150px; }
    .table-wrap { overflow-x: auto; }
    .grid { width: 100%; border-collapse: collapse; font-size: 13px; }
    .grid th { text-align: left; padding: 8px; border-bottom: 2px solid #e2e8f0; color: #475569; }
    .grid td { padding: 8px; border-bottom: 1px solid #f1f5f9; }
    .grid tbody tr { cursor: pointer; }
    .grid tbody tr:hover, .grid tr.selected { background: #f8fafc; }
    .chip { padding: 2px 8px; border-radius: 12px; font-size: 12px; background: #e2e8f0; white-space: nowrap; }
    .s-sent { background: #dcfce7; } .s-dead { background: #fee2e2; } .s-pending, .s-sending { background: #fef9c3; }
    .row-actions { white-space: nowrap; text-align: right; }
    .pager { display: flex; gap: 8px; align-items: center; justify-content: flex-end; margin-top: 8px; }
    .pager span { margin-right: auto; color: #64748b; }
    .detail { border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px; margin-top: 16px; background: #fff; }
    .detail pre { overflow: auto; background: #f8fafc; padding: 8px; border-radius: 4px; }
    .empty { text-align: center; color: #94a3b8; padding: 24px; }
    .error { color: #dc2626; }
  `]
})
export class DeliveriesComponent implements OnInit {
  private api = inject(NotificationsAdminService);
  private snack = inject(MatSnackBar);

  readonly statuses = Object.keys(STATUS_LABELS);
  filters: DeliveryFilters = { channel: '', status: '', recipient: '', date_from: '', date_to: '' };

  items = signal<DeliveryItem[]>([]);
  total = signal(0);
  offset = signal(0);
  detail = signal<DeliveryDetail | null>(null);
  error = signal('');

  ngOnInit(): void {
    this.load();
  }

  label(status: string): string {
    return STATUS_LABELS[status] ?? status;
  }

  search(): void {
    this.offset.set(0);
    this.load();
  }

  page(direction: number): void {
    this.offset.update((o) => Math.max(0, o + direction * PAGE_SIZE));
    this.load();
  }

  load(): void {
    this.error.set('');
    this.api.listDeliveries({ ...this.filters, limit: PAGE_SIZE, offset: this.offset() }).subscribe({
      next: (res) => {
        this.items.set(res.items);
        this.total.set(res.total);
      },
      error: () => this.error.set('Não foi possível carregar as entregas.')
    });
  }

  open(d: DeliveryItem): void {
    this.api.getDelivery(d.id).subscribe({ next: (detail) => this.detail.set(detail) });
  }

  resend(d: DeliveryItem, event: Event): void {
    event.stopPropagation();
    this.api.resend(d.id).subscribe({
      next: () => {
        this.snack.open('Reenvio agendado (nova entrega criada).', 'OK', { duration: 3000 });
        this.load();
      },
      error: () => this.snack.open('Não foi possível reenviar.', 'OK', { duration: 4000 })
    });
  }

  cancel(d: DeliveryItem, event: Event): void {
    event.stopPropagation();
    this.api.cancel(d.id).subscribe({
      next: () => {
        this.snack.open('Entrega cancelada.', 'OK', { duration: 3000 });
        this.load();
      },
      error: () => this.snack.open('Não foi possível cancelar.', 'OK', { duration: 4000 })
    });
  }
}
