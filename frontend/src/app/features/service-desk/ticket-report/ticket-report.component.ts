import { Component, OnInit, inject } from '@angular/core';
import { DatePipe, DecimalPipe, NgTemplateOutlet } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';

import { apiErrorMessage } from '../../../core/http/api-error';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';
import { SLA_PRIORITIES, SlaGroup, SlaService, TicketsReport, formatMinutes } from '../sla.service';

const STATUS_LABELS: Record<string, string> = {
  OPENED: 'Aberto', IN_PROGRESS: 'Em atendimento', PENDING: 'Pendente', RESOLVED: 'Resolvido', CLOSED: 'Encerrado'
};
const PRIORITY_LABELS: Record<string, string> = Object.fromEntries(SLA_PRIORITIES.map((p) => [p.code, p.label]));
const KIND_LABELS: Record<string, string> = { FIRST_RESPONSE: 'Primeira resposta', RESOLUTION: 'Resolução' };

/** Data local em AAAA-MM-DD (o `toISOString` mudaria o dia perto da meia-noite). */
export function isoDay(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Relatório de chamados (ADR-017 P4-S5): volume do período e indicadores de SLA. */
@Component({
  selector: 'app-ticket-report',
  standalone: true,
  imports: [DatePipe, DecimalPipe, NgTemplateOutlet, FormsModule, RouterLink, MatButtonModule, MatIconModule, MatInputModule, LoadStateComponent],
  template: `
    <div class="page">
      <h1>Relatório de chamados</h1>
      <p class="subtitle">
        Volume pelos chamados <strong>abertos</strong> no período; SLA pelos prazos <strong>encerrados</strong> no período
        (só categorias com política). Tempos em horas úteis do calendário da política.
      </p>

      <div class="period">
        <mat-form-field appearance="outline">
          <mat-label>De</mat-label>
          <input matInput type="date" [(ngModel)]="start" data-testid="report-start" />
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Até</mat-label>
          <input matInput type="date" [(ngModel)]="end" data-testid="report-end" />
        </mat-form-field>
        <button mat-flat-button color="primary" (click)="load()" data-testid="report-apply">Aplicar</button>
        <button mat-button (click)="thisMonth()">Este mês</button>
        <button mat-button (click)="lastDays(30)">Últimos 30 dias</button>
        <button mat-button (click)="allTime()">Todo o histórico</button>
      </div>

      <app-load-state [loading]="loading" [error]="error" loadingText="Calculando…" (retry)="load()"></app-load-state>

      @if (report && !loading && !error) {
        <div class="cards" data-testid="report-cards">
          <div class="card"><span class="value">{{ report.total_tickets }}</span><span class="label">Chamados abertos</span></div>
          <div class="card">
            <span class="value">{{ report.total_tickets ? (report.resolution_rate_percent | number:'1.0-1') + '%' : '—' }}</span>
            <span class="label">Já resolvidos ou encerrados</span>
          </div>
          <div class="card highlight" data-testid="report-compliance">
            <span class="value">{{ percent(report.sla.total) }}</span>
            <span class="label">SLA cumprido ({{ report.sla.total.met }} de {{ report.sla.total.met + report.sla.total.breached }})</span>
          </div>
          <div class="card"><span class="value">{{ minutes(report.sla.total.avg_first_response_minutes) }}</span><span class="label">1ª resposta média</span></div>
          <div class="card"><span class="value">{{ minutes(report.sla.total.avg_resolution_minutes) }}</span><span class="label">Resolução média</span></div>
        </div>

        <h2>Agora</h2>
        <div class="cards">
          <div class="card"><span class="value">{{ report.sla.open }}</span><span class="label">Com prazo correndo ou pausado</span></div>
          <div class="card risk"><span class="value">{{ report.sla.at_risk }}</span><span class="label">Em risco</span></div>
          <div class="card late"><span class="value">{{ report.sla.overdue }}</span><span class="label">Atrasados</span></div>
        </div>
        @if (report.sla.attention.length) {
          <table class="grid" data-testid="report-attention">
            <thead><tr><th>Chamado</th><th>Prioridade</th><th>Prazo</th><th>Vence/venceu</th><th>Situação</th></tr></thead>
            <tbody>
              @for (a of report.sla.attention; track a.ticket_id) {
                <tr>
                  <td><a [routerLink]="['/service-desk', a.ticket_id]">{{ a.title }}</a></td>
                  <td>{{ priority(a.priority) }}</td>
                  <td>{{ kind(a.kind) }}</td>
                  <td>{{ a.due_at | date:'dd/MM HH:mm' }}</td>
                  <td><span class="tag" [class.late]="a.overdue" [class.risk]="!a.overdue">{{ a.overdue ? 'Atrasado' : 'Em risco' }}</span></td>
                </tr>
              }
            </tbody>
          </table>
        }

        <h2>SLA por prioridade</h2>
        <ng-container *ngTemplateOutlet="slaTable; context: { $implicit: report.sla.by_priority }"></ng-container>
        <h2>SLA por categoria</h2>
        <ng-container *ngTemplateOutlet="slaTable; context: { $implicit: report.sla.by_category }"></ng-container>

        <h2>Chamados abertos no período</h2>
        <div class="split">
          <table class="grid">
            <thead><tr><th>Status</th><th>Qtd.</th></tr></thead>
            <tbody>
              @for (s of statusRows(); track s.key) { <tr><td>{{ s.label }}</td><td>{{ s.count }}</td></tr> }
            </tbody>
          </table>
          <table class="grid">
            <thead><tr><th>Categoria</th><th>Qtd.</th></tr></thead>
            <tbody>
              @for (c of report.by_category; track c.category) { <tr><td>{{ c.category }}</td><td>{{ c.count }}</td></tr> }
              @empty { <tr><td colspan="2" class="muted">Nenhum chamado no período.</td></tr> }
            </tbody>
          </table>
        </div>
      }

      <ng-template #slaTable let-rows>
        <table class="grid">
          <thead><tr><th></th><th>Cumpridos</th><th>Violados</th><th>Cumprimento</th><th>1ª resposta média</th><th>Resolução média</th></tr></thead>
          <tbody>
            @for (g of rows; track g.key) {
              <tr>
                <td>{{ g.label }}</td><td>{{ g.met }}</td><td>{{ g.breached }}</td><td>{{ percent(g) }}</td>
                <td>{{ minutes(g.avg_first_response_minutes) }}</td><td>{{ minutes(g.avg_resolution_minutes) }}</td>
              </tr>
            } @empty {
              <tr><td colspan="6" class="muted">Nenhum prazo encerrado no período.</td></tr>
            }
          </tbody>
        </table>
      </ng-template>
    </div>
  `,
  styles: [`
    .page { max-width: 1100px; margin: 0 auto; padding: 24px 16px; }
    h1 { margin: 0; font-size: 24px; }
    h2 { margin: 24px 0 8px; font-size: 18px; }
    .subtitle { margin: 4px 0 16px; color: #64748b; }
    .period { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(170px, 1fr)); gap: 12px; }
    .card { display: flex; flex-direction: column; gap: 4px; padding: 14px; border: 1px solid #e2e8f0; border-radius: 10px; background: #fff; }
    .card .value { font-size: 24px; font-weight: 600; }
    .card .label { font-size: 13px; color: #64748b; }
    .card.highlight { border-color: #93c5fd; }
    .card.risk .value { color: #92400e; }
    .card.late .value { color: #991b1b; }
    .grid { width: 100%; border-collapse: collapse; background: #fff; margin-top: 8px; }
    .grid th, .grid td { text-align: left; padding: 8px; border-bottom: 1px solid #e2e8f0; font-size: 14px; }
    .grid th { color: #475569; font-weight: 500; }
    .split { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 16px; }
    .tag { padding: 2px 8px; border-radius: 10px; font-size: 12px; }
    .tag.late { background: #fee2e2; color: #991b1b; }
    .tag.risk { background: #fef3c7; color: #92400e; }
    .muted { color: #94a3b8; }
  `]
})
export class TicketReportComponent implements OnInit {
  private sla = inject(SlaService);

  start = '';
  end = '';
  report: TicketsReport | null = null;
  loading = false;
  error: string | null = null;

  ngOnInit() {
    this.thisMonth();
  }

  thisMonth() {
    const today = new Date();
    this.start = isoDay(new Date(today.getFullYear(), today.getMonth(), 1));
    this.end = isoDay(today);
    this.load();
  }

  lastDays(days: number) {
    const today = new Date();
    this.start = isoDay(new Date(today.getFullYear(), today.getMonth(), today.getDate() - (days - 1)));
    this.end = isoDay(today);
    this.load();
  }

  allTime() {
    this.start = this.end = '';
    this.load();
  }

  load() {
    this.loading = true;
    this.error = null;
    this.sla.ticketsReport(this.start || undefined, this.end || undefined).subscribe({
      next: (r) => {
        this.report = r;
        this.loading = false;
      },
      error: (err) => {
        this.error = apiErrorMessage(err, 'Não foi possível gerar o relatório.');
        this.loading = false;
      }
    });
  }

  percent(g: SlaGroup): string {
    return g.compliance_percent === null ? '—' : `${g.compliance_percent.toLocaleString('pt-BR')}%`;
  }

  minutes(value: number | null): string {
    return value === null ? '—' : formatMinutes(value);
  }

  priority(code: string): string {
    return PRIORITY_LABELS[code] ?? code;
  }

  kind(code: string): string {
    return KIND_LABELS[code] ?? code;
  }

  statusRows() {
    const counts = this.report?.by_status ?? {};
    return Object.keys(STATUS_LABELS).map((key) => ({ key, label: STATUS_LABELS[key], count: counts[key] ?? 0 }));
  }
}
