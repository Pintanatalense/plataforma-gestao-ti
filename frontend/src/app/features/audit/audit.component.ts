import { ChangeDetectorRef, Component, OnInit, inject } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { apiErrorMessage } from '../../core/http/api-error';
import { AuditFilters, AuditLogEntry, AuditService } from '../../core/services/audit.service';
import { LoadStateComponent } from '../../shared/components/load-state/load-state.component';

const PAGE_SIZE = 50;

/** Nomes legíveis dos eventos conhecidos; os demais aparecem com o código técnico. */
const EVENT_LABELS: Record<string, string> = {
  'identity.login_success': 'Login realizado',
  'identity.login_failed': 'Falha de login',
  'identity.login_blocked': 'Login bloqueado (conta travada)',
  'identity.user_created': 'Usuário criado',
  'identity.user_updated': 'Usuário alterado',
  'identity.user_deactivated': 'Usuário inativado',
  'identity.password_reset_by_admin': 'Senha redefinida por administrador',
  'identity.password_changed': 'Senha trocada pelo usuário',
  'identity.password_reset_requested': 'Recuperação de senha solicitada',
  'identity.password_reset_completed': 'Recuperação de senha concluída',
  'identity.password_reset_send_failed': 'Falha ao enviar e-mail de recuperação',
  'identity.password_reset_configured': 'Recuperação de senha ativada/desativada',
  'identity.role_created': 'Perfil criado',
  'identity.role_updated': 'Perfil alterado',
  'identity.role_deleted': 'Perfil removido',
  'organization.company_updated': 'Dados da empresa alterados',
  'organization.company_logo_updated': 'Logomarca alterada',
  'notifications.email_configured': 'SMTP configurado'
};

@Component({
  selector: 'app-audit',
  standalone: true,
  imports: [CommonModule, FormsModule, DatePipe, MatButtonModule, MatIconModule, LoadStateComponent],
  template: `
    <div class="page-container">
      <div class="page-header">
        <div class="title-area">
          <h1>Auditoria</h1>
          <p class="subtitle">Quem fez o quê e quando (mais recentes primeiro). Senhas e tokens nunca são registrados.</p>
        </div>
      </div>

      <form class="filters" (ngSubmit)="apply()" data-testid="audit-filters">
        <label>Evento
          <select name="event_type" [(ngModel)]="filters.event_type" data-testid="filter-event">
            <option value="">Todos</option>
            @for (type of eventTypes; track type) {
              <option [value]="type">{{ label(type) }}</option>
            }
          </select>
        </label>
        <label>Usuário
          <input name="user" [(ngModel)]="filters.user" placeholder="trecho do e-mail" data-testid="filter-user" />
        </label>
        <label>De
          <input type="date" name="date_from" [(ngModel)]="filters.date_from" data-testid="filter-from" />
        </label>
        <label>Até
          <input type="date" name="date_to" [(ngModel)]="filters.date_to" data-testid="filter-to" />
        </label>
        <button mat-flat-button color="primary" type="submit" data-testid="filter-apply">Filtrar</button>
        <button mat-stroked-button type="button" (click)="clear()" data-testid="filter-clear">Limpar</button>
      </form>

      <app-load-state [loading]="isLoading" [error]="loadError" [empty]="entries.length === 0"
                      emptyText="Nenhum registro para esses filtros." loadingText="Carregando auditoria…" (retry)="load()">
        <div class="table-wrap">
          <table class="audit-table" data-testid="audit-table">
            <thead><tr><th>Data/hora</th><th>Usuário</th><th>Evento</th><th>Entidade</th><th>Detalhes</th></tr></thead>
            <tbody>
              @for (e of entries; track e.id) {
                <tr>
                  <td>{{ e.created_at | date: 'dd/MM/yyyy HH:mm:ss' }}</td>
                  <td>{{ e.user_email || 'Sistema / não identificado' }}</td>
                  <td [title]="e.event_type">{{ label(e.event_type) }}</td>
                  <td>{{ e.entity_type }}</td>
                  <td class="details">{{ details(e) }}</td>
                </tr>
              }
            </tbody>
          </table>
        </div>
        <div class="pager">
          <span data-testid="audit-range">{{ rangeText }}</span>
          <button mat-stroked-button type="button" [disabled]="offset === 0" (click)="go(-1)" data-testid="page-prev">
            <mat-icon>chevron_left</mat-icon> Anterior
          </button>
          <button mat-stroked-button type="button" [disabled]="offset + entries.length >= total" (click)="go(1)" data-testid="page-next">
            Próxima <mat-icon>chevron_right</mat-icon>
          </button>
        </div>
      </app-load-state>
    </div>
  `,
  styles: [
    `
      .filters { display: flex; gap: 12px; flex-wrap: wrap; align-items: flex-end; margin-bottom: 16px; }
      .filters label { display: flex; flex-direction: column; gap: 4px; font-size: 12px; color: #475569; }
      .filters select, .filters input { padding: 8px; border: 1px solid #cbd5e1; border-radius: 6px; font-size: 14px; min-width: 160px; }
      .table-wrap { overflow-x: auto; background: #fff; border-radius: 12px; box-shadow: 0 1px 3px rgba(0,0,0,.12); }
      .audit-table { width: 100%; border-collapse: collapse; font-size: 13px; }
      .audit-table th, .audit-table td { padding: 10px 12px; text-align: left; border-bottom: 1px solid #e2e8f0; vertical-align: top; }
      .audit-table th { background: #f8fafc; font-weight: 600; }
      .details { color: #475569; max-width: 420px; word-break: break-word; }
      .pager { display: flex; gap: 12px; align-items: center; justify-content: flex-end; margin-top: 12px; font-size: 13px; }
    `
  ]
})
export class AuditComponent implements OnInit {
  private audit = inject(AuditService);
  private cdr = inject(ChangeDetectorRef);

  filters: AuditFilters & { event_type: string; user: string; date_from: string; date_to: string } = {
    event_type: '', user: '', date_from: '', date_to: ''
  };
  eventTypes: string[] = [];
  entries: AuditLogEntry[] = [];
  total = 0;
  offset = 0;
  isLoading = true;
  loadError: string | null = null;
  /** Filtros aplicados na última busca (a paginação não deve usar o que foi digitado e ainda não aplicado). */
  private applied: AuditFilters = {};

  ngOnInit(): void {
    this.audit.eventTypes().subscribe({
      next: (types) => {
        this.eventTypes = types;
        this.cdr.markForCheck();
      },
      error: () => {} // o filtro de evento fica só com "Todos"; a lista em si mostra o erro, se houver
    });
    this.load();
  }

  label(type: string): string {
    return EVENT_LABELS[type] ?? type;
  }

  details(e: AuditLogEntry): string {
    const parts = Object.entries(e.data ?? {}).map(([k, v]) => `${k}: ${Array.isArray(v) ? v.join(', ') : String(v)}`);
    return parts.join(' · ');
  }

  get rangeText(): string {
    if (this.total === 0) return '0 registros';
    return `${this.offset + 1}–${this.offset + this.entries.length} de ${this.total}`;
  }

  apply(): void {
    this.applied = { ...this.filters };
    this.offset = 0;
    this.load();
  }

  clear(): void {
    this.filters = { event_type: '', user: '', date_from: '', date_to: '' };
    this.apply();
  }

  go(direction: 1 | -1): void {
    this.offset = Math.max(0, this.offset + direction * PAGE_SIZE);
    this.load();
  }

  load(): void {
    this.isLoading = true;
    this.loadError = null;
    this.audit.list(this.applied, PAGE_SIZE, this.offset).subscribe({
      next: (page) => {
        this.entries = page.items;
        this.total = page.total;
        this.isLoading = false;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.entries = [];
        this.total = 0;
        this.isLoading = false;
        this.loadError = apiErrorMessage(err, 'Não foi possível carregar a auditoria.');
        this.cdr.markForCheck();
      }
    });
  }
}
