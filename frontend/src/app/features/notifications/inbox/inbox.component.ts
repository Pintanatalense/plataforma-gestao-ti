import { Component, DestroyRef, OnInit, inject, signal } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatInputModule } from '@angular/material/input';
import { Notification, NotificationFilters, NotificationsService } from '../../../core/services/notifications.service';

const PAGE_SIZE = 25;

/** Rota de destino de uma notificação, a partir da entidade de origem. */
export function notificationLink(n: Pick<Notification, 'entity_type' | 'entity_id'>): string[] | null {
  if (n.entity_type === 'ticket' && n.entity_id) return ['/service-desk', n.entity_id];
  return null;
}

@Component({
  selector: 'app-inbox',
  standalone: true,
  imports: [
    CommonModule, FormsModule, RouterLink, DatePipe,
    MatButtonModule, MatIconModule, MatFormFieldModule, MatSelectModule, MatInputModule
  ],
  template: `
    <div class="page">
      <header class="page-header">
        <div>
          <h1>Caixa de entrada</h1>
          <p class="subtitle">{{ unread() }} não lida(s)</p>
        </div>
        <div class="actions">
          <a mat-stroked-button routerLink="/notifications/preferences"><mat-icon>tune</mat-icon> Preferências</a>
          <button mat-flat-button color="primary" (click)="markAll()" [disabled]="unread() === 0">
            <mat-icon>done_all</mat-icon> Marcar todas como lidas
          </button>
        </div>
      </header>

      <section class="filters">
        <mat-form-field appearance="outline">
          <mat-label>Situação</mat-label>
          <mat-select [(ngModel)]="status" (selectionChange)="reload()" data-testid="filter-status">
            <mat-option value="all">Todas</mat-option>
            <mat-option value="unread">Não lidas</mat-option>
            <mat-option value="read">Lidas</mat-option>
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Tipo</mat-label>
          <mat-select [(ngModel)]="type" (selectionChange)="reload()">
            <mat-option value="">Todos</mat-option>
            <mat-option value="info">Informação</mat-option>
            <mat-option value="warning">Atenção</mat-option>
            <mat-option value="error">Crítico</mat-option>
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>De</mat-label>
          <input matInput type="date" [(ngModel)]="dateFrom" (change)="reload()" />
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Até</mat-label>
          <input matInput type="date" [(ngModel)]="dateTo" (change)="reload()" />
        </mat-form-field>
      </section>

      @if (error()) {
        <p class="error" role="alert">{{ error() }}</p>
      }

      <ul class="list" aria-live="polite">
        @for (n of items(); track n.id) {
          <li class="item" [class.unread]="!n.is_read" [class]="'type-' + n.type" data-testid="notification-item">
            <mat-icon class="icon">{{ iconFor(n.type) }}</mat-icon>
            <div class="body">
              <strong>{{ n.title }}</strong>
              <span class="message">{{ n.message }}</span>
              <span class="time">{{ n.created_at | date: 'dd/MM/yyyy HH:mm' }}</span>
            </div>
            <div class="row-actions">
              @if (link(n); as target) {
                <button mat-button (click)="open(n)">Abrir</button>
              }
              @if (!n.is_read) {
                <button mat-icon-button (click)="markRead(n)" aria-label="Marcar como lida">
                  <mat-icon>done</mat-icon>
                </button>
              }
            </div>
          </li>
        } @empty {
          @if (!loading() && !error()) {
            <li class="empty">
              <mat-icon>notifications_none</mat-icon>
              <p>Nenhuma notificação com esses filtros.</p>
            </li>
          }
        }
      </ul>

      @if (hasMore()) {
        <div class="more"><button mat-stroked-button (click)="loadMore()" [disabled]="loading()">Carregar mais</button></div>
      }
    </div>
  `,
  styles: [`
    .page { max-width: 880px; margin: 0 auto; padding: 24px 16px; }
    .page-header { display: flex; flex-wrap: wrap; gap: 12px; justify-content: space-between; align-items: center; }
    h1 { margin: 0; font-size: 24px; }
    .subtitle { margin: 4px 0 0; color: #64748b; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .filters { display: flex; flex-wrap: wrap; gap: 12px; margin-top: 16px; }
    .filters mat-form-field { flex: 1 1 160px; }
    .list { list-style: none; margin: 8px 0; padding: 0; display: flex; flex-direction: column; gap: 8px; }
    .item { display: flex; gap: 12px; align-items: flex-start; padding: 12px 16px; border: 1px solid #e2e8f0; border-radius: 8px; background: #fff; }
    .item.unread { border-left: 4px solid #2563eb; background: #f8fafc; }
    .item.type-error .icon { color: #dc2626; }
    .item.type-warning .icon { color: #d97706; }
    .item.type-info .icon { color: #2563eb; }
    .body { display: flex; flex-direction: column; flex: 1; min-width: 0; gap: 2px; }
    .message { color: #475569; white-space: pre-wrap; overflow-wrap: anywhere; }
    .time { color: #94a3b8; font-size: 12px; }
    .row-actions { display: flex; align-items: center; }
    .empty { text-align: center; color: #94a3b8; padding: 32px 0; list-style: none; }
    .more { text-align: center; margin: 16px 0; }
    .error { color: #dc2626; }
  `]
})
export class InboxComponent implements OnInit {
  private service = inject(NotificationsService);
  private router = inject(Router);
  private destroyRef = inject(DestroyRef);

  items = signal<Notification[]>([]);
  unread = signal(0);
  loading = signal(false);
  hasMore = signal(false);
  error = signal('');

  status: 'all' | 'unread' | 'read' = 'all';
  type = '';
  dateFrom = '';
  dateTo = '';

  ngOnInit(): void {
    this.reload();
    this.service.newNotification$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.reload());
    this.service.reconnected$.pipe(takeUntilDestroyed(this.destroyRef)).subscribe(() => this.reload());
  }

  private filters(offset: number): NotificationFilters {
    return {
      is_read: this.status === 'all' ? undefined : this.status === 'read',
      type: this.type || undefined,
      date_from: this.dateFrom || undefined,
      date_to: this.dateTo || undefined,
      limit: PAGE_SIZE,
      offset
    };
  }

  reload(): void {
    this.loading.set(true);
    this.error.set('');
    this.service.list(this.filters(0)).subscribe({
      next: (list) => {
        this.items.set(list);
        this.hasMore.set(list.length === PAGE_SIZE);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Não foi possível carregar as notificações.');
        this.loading.set(false);
      }
    });
    this.refreshUnread();
  }

  loadMore(): void {
    this.loading.set(true);
    this.error.set('');
    this.service.list(this.filters(this.items().length)).subscribe({
      next: (list) => {
        this.items.update((current) => [...current, ...list]);
        this.hasMore.set(list.length === PAGE_SIZE);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Não foi possível carregar mais notificações.');
        this.loading.set(false);
      }
    });
  }

  private refreshUnread(): void {
    this.service.unreadCount().subscribe({ next: (r) => this.unread.set(r.count), error: () => {} });
  }

  iconFor(type: string): string {
    return type === 'error' ? 'error' : type === 'warning' ? 'warning' : 'info';
  }

  link(n: Notification): string[] | null {
    return notificationLink(n);
  }

  markRead(n: Notification): void {
    this.service.markAsRead(n.id).subscribe(() => {
      this.items.update((list) => list.map((x) => (x.id === n.id ? { ...x, is_read: true } : x)));
      this.refreshUnread();
    });
  }

  open(n: Notification): void {
    const target = notificationLink(n);
    if (!n.is_read) this.markRead(n);
    if (target) this.router.navigate(target);
  }

  markAll(): void {
    this.service.markAllAsRead().subscribe(() => this.reload());
  }
}
