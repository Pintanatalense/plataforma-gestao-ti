import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { apiErrorMessage } from '../../../core/http/api-error';
import { MessageSchedule, MessageScheduleDetail, MessagesService } from '../../../core/services/messages.service';
import { CHANNEL_NAMES } from '../admin/channels.component';
import { deliverySummary } from './history.component';

export const SCHEDULE_STATUS_LABELS: Record<string, string> = {
  ACTIVE: 'Ativo',
  PAUSED: 'Pausado',
  DONE: 'Encerrado',
  CANCELLED: 'Cancelado'
};

export const LAST_OUTCOME_LABELS: Record<string, string> = {
  sent: 'Enviado',
  failed: 'Falhou',
  missed: 'Perdido (atraso)'
};

const WEEKDAYS = ['seg', 'ter', 'qua', 'qui', 'sex', 'sáb', 'dom'];

/** A regra em uma frase: "Todo dia às 09:00", "Seg, qua às 08:30", "Todo dia 5 às 10:00 · dias úteis". */
export function describeRule(s: Pick<MessageSchedule, 'recurrence' | 'run_at' | 'time_of_day' | 'weekdays' | 'month_day' | 'calendar_id' | 'non_business_rule'>): string {
  let text: string;
  if (s.recurrence === 'once') {
    text = 'Uma vez';
  } else if (s.recurrence === 'daily') {
    text = `Todo dia às ${s.time_of_day}`;
  } else if (s.recurrence === 'weekly') {
    const days = s.weekdays.map((d) => WEEKDAYS[d]).join(', ');
    text = `${days.charAt(0).toUpperCase()}${days.slice(1)} às ${s.time_of_day}`;
  } else {
    text = `Todo dia ${s.month_day} às ${s.time_of_day}`;
  }
  if (s.calendar_id) text += s.non_business_rule === 'next' ? ' · dia não útil vai para o próximo' : ' · só dias úteis';
  return text;
}

@Component({
  selector: 'app-message-schedules',
  standalone: true,
  imports: [DatePipe, FormsModule, MatButtonModule, MatFormFieldModule, MatSelectModule, MatSnackBarModule],
  template: `
    <div class="toolbar">
      <mat-form-field appearance="outline">
        <mat-label>Situação</mat-label>
        <mat-select [(ngModel)]="status" (selectionChange)="load()" data-testid="schedules-status">
          <mat-option value="">Todas</mat-option>
          @for (s of statuses; track s.key) { <mat-option [value]="s.key">{{ s.label }}</mat-option> }
        </mat-select>
      </mat-form-field>
    </div>
    @if (error()) {
      <p class="error" role="alert">{{ error() }}</p>
    }
    <div class="table-wrap">
      <table class="grid" data-testid="schedules-table">
        <thead><tr><th>Nome</th><th>Quando</th><th>Canal</th><th>Próximo envio</th><th>Último</th><th>Situação</th><th></th></tr></thead>
        <tbody>
          @for (s of items(); track s.id) {
            <tr (click)="open(s)" [class.selected]="detail()?.id === s.id" data-testid="schedule-row">
              <td>{{ s.name }}</td>
              <td>{{ rule(s) }}</td>
              <td>{{ channelName(s.channel) }}</td>
              <td>{{ s.status === 'ACTIVE' ? (s.next_run_at | date: 'dd/MM/yyyy HH:mm') : '—' }}</td>
              <td [title]="s.last_error || ''">
                {{ s.last_outcome ? outcomeLabel(s.last_outcome) : '—' }}
                @if (s.last_error) { <span class="warn" data-testid="schedule-error">· {{ s.last_error }}</span> }
              </td>
              <td>{{ statusLabel(s.status) }}</td>
              <td class="row-actions">
                @if (s.status === 'ACTIVE') {
                  <button mat-button (click)="act(s, 'pause', $event)" data-testid="schedule-pause">Pausar</button>
                }
                @if (s.status === 'PAUSED') {
                  <button mat-button (click)="act(s, 'resume', $event)" data-testid="schedule-resume">Retomar</button>
                }
                @if (s.status === 'ACTIVE' || s.status === 'PAUSED') {
                  <button mat-button color="warn" (click)="act(s, 'cancel', $event)" data-testid="schedule-cancel">Cancelar</button>
                }
              </td>
            </tr>
          } @empty {
            <tr><td colspan="7" class="empty">Nenhum agendamento.</td></tr>
          }
        </tbody>
      </table>
    </div>

    @if (detail(); as d) {
      <section class="detail" data-testid="schedule-detail">
        <h3>{{ d.name }}</h3>
        <p class="hint">{{ rule(d) }} · fuso {{ d.timezone }} · {{ d.recipient_count }} destinatário(s) · {{ d.runs_count }} envio(s) feitos</p>
        <pre>{{ d.subject ? d.subject + '\n\n' : '' }}{{ d.body }}</pre>
        @if (d.upcoming.length) {
          <h4>Próximos envios</h4>
          <ul>@for (u of d.upcoming; track u) { <li>{{ u | date: 'EEE dd/MM/yyyy HH:mm' }}</li> }</ul>
        }
        <h4>Envios feitos</h4>
        <ul>
          @for (r of d.runs; track r.id) {
            <li>{{ r.scheduled_for | date: 'dd/MM/yyyy HH:mm' }} — {{ summary(r.deliveries) }}</li>
          } @empty {
            <li class="empty-item">Nenhum ainda. Envios aparecem também no Histórico.</li>
          }
        </ul>
      </section>
    }
  `,
  styles: [`
    .toolbar { margin-top: 16px; }
    .table-wrap { overflow-x: auto; }
    .grid { width: 100%; border-collapse: collapse; font-size: 13px; }
    .grid th { text-align: left; padding: 8px; border-bottom: 2px solid #e2e8f0; color: #475569; }
    .grid td { padding: 8px; border-bottom: 1px solid #f1f5f9; }
    .grid tbody tr { cursor: pointer; }
    .grid tbody tr:hover, .grid tr.selected { background: #f8fafc; }
    .row-actions { text-align: right; white-space: nowrap; }
    .detail { border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px; margin-top: 16px; background: #fff; }
    .detail pre { white-space: pre-wrap; background: #f8fafc; padding: 8px; border-radius: 4px; }
    .warn { color: #b45309; }
    .hint, .empty-item { color: #64748b; }
    .empty { text-align: center; color: #94a3b8; padding: 24px; }
    .error { color: #dc2626; }
  `]
})
export class MessageSchedulesComponent implements OnInit {
  private api = inject(MessagesService);
  private snack = inject(MatSnackBar);

  readonly statuses = Object.entries(SCHEDULE_STATUS_LABELS).map(([key, label]) => ({ key, label }));
  status = '';
  items = signal<MessageSchedule[]>([]);
  detail = signal<MessageScheduleDetail | null>(null);
  error = signal('');

  ngOnInit(): void {
    this.load();
  }

  channelName(channel: string): string {
    return CHANNEL_NAMES[channel] ?? channel;
  }

  statusLabel(status: string): string {
    return SCHEDULE_STATUS_LABELS[status] ?? status;
  }

  outcomeLabel(outcome: string): string {
    return LAST_OUTCOME_LABELS[outcome] ?? outcome;
  }

  rule(s: MessageSchedule): string {
    return describeRule(s);
  }

  summary(counts: Record<string, number>): string {
    return deliverySummary(counts);
  }

  load(): void {
    this.error.set('');
    this.api.listSchedules(this.status || undefined).subscribe({
      next: (res) => this.items.set(res.items),
      error: (err) => this.error.set(apiErrorMessage(err, 'Não foi possível carregar os agendamentos.'))
    });
  }

  open(s: MessageSchedule): void {
    this.api.getSchedule(s.id).subscribe({ next: (d) => this.detail.set(d) });
  }

  act(s: MessageSchedule, action: 'pause' | 'resume' | 'cancel', event: Event): void {
    event.stopPropagation();
    if (action === 'cancel' && !confirm(`Cancelar "${s.name}"? Nenhum envio futuro sairá.`)) return;
    const done = { pause: 'Agendamento pausado.', resume: 'Agendamento retomado.', cancel: 'Agendamento cancelado.' }[action];
    this.api.scheduleAction(s.id, action).subscribe({
      next: () => {
        this.snack.open(done, 'OK', { duration: 3000 });
        this.detail.set(null);
        this.load();
      },
      error: (err) => this.snack.open(apiErrorMessage(err, 'Não foi possível concluir.'), 'OK', { duration: 4000 })
    });
  }
}
