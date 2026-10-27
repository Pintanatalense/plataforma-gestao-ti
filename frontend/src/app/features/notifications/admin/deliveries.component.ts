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
import { CHANNEL_NAMES } from './channels.component';

const PAGE_SIZE = 25;

export const STATUS_LABELS: Record<string, string> = {
  PENDING: 'Pendente',
  SENDING: 'Enviando',
  // SENT = o gateway aceitou; entregue/lida só quando o provedor confirma (coluna "Confirmação", ADR-025 §2).
  SENT: 'Aceita pelo gateway',
  DEAD: 'Falhou (definitivo)',
  SKIPPED: 'Ignorada',
  CANCELLED: 'Cancelada'
};

export const PROVIDER_STATUS_LABELS: Record<string, string> = {
  accepted: 'Recebida pelo provedor',
  delivered: 'Entregue',
  read: 'Lida',
  failed: 'Falhou no provedor'
};

export const ORIGIN_LABELS: Record<string, string> = {
  rule: 'Regra',
  direct: 'Mensagem direta',
  conversation: 'Resposta do robô',
  system: 'Sistema'
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
          @for (c of channels; track c.key) {
            <mat-option [value]="c.key">{{ c.label }}</mat-option>
          }
        </mat-select>
      </mat-form-field>
      <mat-form-field appearance="outline">
        <mat-label>Origem</mat-label>
        <mat-select [(ngModel)]="filters.origin" (selectionChange)="search()" data-testid="f-origin">
          <mat-option value="">Todas</mat-option>
          @for (o of origins; track o.key) {
            <mat-option [value]="o.key">{{ o.label }}</mat-option>
          }
        </mat-select>
      </mat-form-field>
      <mat-form-field appearance="outline">
        <mat-label>Confirmação</mat-label>
        <mat-select [(ngModel)]="filters.provider_status" (selectionChange)="search()" data-testid="f-provider-status">
          <mat-option value="">Todas</mat-option>
          @for (p of providerStatuses; track p.key) {
            <mat-option [value]="p.key">{{ p.label }}</mat-option>
          }
          <mat-option value="none">Sem confirmação</mat-option>
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
        <mat-label>Endereço (telefone, chat)</mat-label>
        <input matInput [(ngModel)]="filters.address" (keyup.enter)="search()" maxlength="255" />
      </mat-form-field>
      <mat-form-field appearance="outline">
        <mat-label>Texto da mensagem</mat-label>
        <input matInput [(ngModel)]="filters.q" (keyup.enter)="search()" maxlength="100" data-testid="f-q" />
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
          <tr><th>Quando</th><th>Evento</th><th>Destinatário</th><th>Canal</th><th>Situação</th><th>Confirmação</th><th>Tent.</th><th></th></tr>
        </thead>
        <tbody>
          @for (d of items(); track d.id) {
            <tr [class.selected]="detail()?.id === d.id" (click)="open(d)" data-testid="delivery-row">
              <td>{{ d.created_at | date: 'dd/MM HH:mm' }}</td>
              <td>{{ d.event_type }}</td>
              <td>{{ d.recipient_email || d.address }}</td>
              <td>{{ channelName(d.channel) }}</td>
              <td><span class="chip" [class]="'s-' + d.status.toLowerCase()">{{ label(d.status) }}</span></td>
              <td data-testid="provider-status">
                @if (d.provider_status) {
                  <span class="chip" [class]="'p-' + d.provider_status">{{ providerLabel(d.provider_status) }}</span>
                } @else {
                  <span class="muted">—</span>
                }
              </td>
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
            <tr><td colspan="8" class="empty">Nenhuma entrega encontrada.</td></tr>
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
        <p><strong>Para:</strong> {{ d.recipient_email || d.address }} · <strong>Canal:</strong> {{ channelName(d.channel) }} ·
          <strong>Prioridade:</strong> {{ d.priority }} · <strong>Origem:</strong> {{ originLabel(d.origin) }}</p>
        <p data-testid="detail-confirmation"><strong>Confirmação do provedor:</strong>
          @if (d.provider_status) {
            {{ providerLabel(d.provider_status) }} em {{ d.provider_status_at | date: 'dd/MM HH:mm:ss' }}
          } @else if (d.status === 'SENT') {
            nenhuma (o canal não informa ou ainda não informou; a mensagem foi aceita pelo gateway)
          } @else {
            —
          }
        </p>
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
    .p-delivered, .p-read { background: #dcfce7; } .p-failed { background: #fee2e2; } .p-accepted { background: #e0f2fe; }
    .muted { color: #94a3b8; }
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
  readonly channels = Object.entries(CHANNEL_NAMES).map(([key, label]) => ({ key, label }));
  readonly origins = Object.entries(ORIGIN_LABELS).map(([key, label]) => ({ key, label }));
  readonly providerStatuses = Object.entries(PROVIDER_STATUS_LABELS).map(([key, label]) => ({ key, label }));
  filters: DeliveryFilters = {
    channel: '', status: '', recipient: '', date_from: '', date_to: '', origin: '', provider_status: '', address: '', q: ''
  };

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

  providerLabel(status: string): string {
    return PROVIDER_STATUS_LABELS[status] ?? status;
  }

  originLabel(origin: string): string {
    return ORIGIN_LABELS[origin] ?? origin;
  }

  channelName(channel: string): string {
    return CHANNEL_NAMES[channel] ?? channel;
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
