import { Component, OnInit, inject, signal } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { apiErrorMessage } from '../../../core/http/api-error';
import { MatInputModule } from '@angular/material/input';
import {
  BusinessCalendarOption,
  MessageSchedule,
  MessageScheduleDetail,
  MessagesService,
  ScheduleRule
} from '../../../core/services/messages.service';
import { CHANNEL_NAMES } from '../admin/channels.component';
import { deliverySummary } from './history.component';
import { ScheduleRuleFieldsComponent, ruleBodyOf, toLocalInput } from './schedule-rule-fields.component';

interface ScheduleEdit {
  source: MessageScheduleDetail;
  name: string;
  subject: string;
  body: string;
  priority: 'low' | 'normal' | 'high';
  rule: ScheduleRule;
  runAtLocal: string;
}

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
  imports: [DatePipe, FormsModule, MatButtonModule, MatFormFieldModule, MatInputModule, MatSelectModule, MatSnackBarModule, ScheduleRuleFieldsComponent],
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

    @if (editing(); as e) {
      <section class="detail" data-testid="schedule-edit">
        <h3>Editar agendamento</h3>
        <p class="hint">Canal e destinatários continuam os mesmos; para trocá-los, cancele e crie outro.</p>
        <div class="row">
          <mat-form-field appearance="outline">
            <mat-label>Nome</mat-label>
            <input matInput [(ngModel)]="e.name" maxlength="150" data-testid="edit-name" />
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Prioridade</mat-label>
            <mat-select [(ngModel)]="e.priority">
              <mat-option value="low">Baixa</mat-option>
              <mat-option value="normal">Normal</mat-option>
              <mat-option value="high">Alta</mat-option>
            </mat-select>
          </mat-form-field>
        </div>
        <mat-form-field appearance="outline" class="full">
          <mat-label>Assunto</mat-label>
          <input matInput [(ngModel)]="e.subject" maxlength="200" />
        </mat-form-field>
        <mat-form-field appearance="outline" class="full">
          <mat-label>Mensagem</mat-label>
          <textarea matInput rows="5" [(ngModel)]="e.body" maxlength="4000" data-testid="edit-body"></textarea>
        </mat-form-field>
        <app-schedule-rule-fields [rule]="e.rule" [(runAt)]="e.runAtLocal" [calendars]="calendars()" (changed)="editDates.set([])" />
        <button mat-stroked-button (click)="loadEditDates()" data-testid="edit-occurrences">Ver próximas datas</button>
        @if (editDates().length) {
          <ul data-testid="edit-dates">@for (u of editDates(); track u) { <li>{{ u | date: 'EEE dd/MM/yyyy HH:mm' }}</li> }</ul>
        }
        @if (editError()) {
          <p class="error" role="alert">{{ editError() }}</p>
        }
        <div class="footer">
          <button mat-button (click)="editing.set(null)">Cancelar</button>
          <button mat-flat-button color="primary" (click)="saveEdit()" [disabled]="saving()" data-testid="edit-save">Salvar</button>
        </div>
      </section>
    } @else if (detail(); as d) {
      <section class="detail" data-testid="schedule-detail">
        <h3>{{ d.name }}
          @if (d.status === 'ACTIVE' || d.status === 'PAUSED') {
            <button mat-stroked-button (click)="startEdit(d)" data-testid="schedule-edit-start">Editar</button>
          }
        </h3>
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
    .detail h3 { display: flex; align-items: center; gap: 12px; }
    .row { display: flex; flex-wrap: wrap; gap: 12px; }
    .row mat-form-field { flex: 1 1 180px; }
    .full { width: 100%; }
    .footer { display: flex; justify-content: flex-end; gap: 8px; }
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
  editing = signal<ScheduleEdit | null>(null);
  editDates = signal<string[]>([]);
  editError = signal('');
  saving = signal(false);
  calendars = signal<BusinessCalendarOption[]>([]);

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
    this.editing.set(null);
    this.api.getSchedule(s.id).subscribe({ next: (d) => this.detail.set(d) });
  }

  startEdit(d: MessageScheduleDetail): void {
    this.editError.set('');
    this.editDates.set([]);
    if (!this.calendars().length) {
      this.api.calendars().subscribe({ next: (res) => this.calendars.set(res.items), error: () => this.calendars.set([]) });
    }
    this.editing.set({
      source: d, name: d.name, subject: d.subject, body: d.body, priority: d.priority as ScheduleEdit['priority'],
      runAtLocal: toLocalInput(d.run_at),
      rule: {
        recurrence: d.recurrence, run_at: d.run_at, time_of_day: d.time_of_day ?? '09:00', weekdays: [...d.weekdays],
        month_day: d.month_day ?? 1, starts_on: d.starts_on, ends_on: d.ends_on, calendar_id: d.calendar_id,
        non_business_rule: d.non_business_rule
      }
    });
  }

  loadEditDates(): void {
    const e = this.editing();
    if (!e) return;
    this.api.occurrences(ruleBodyOf(e.rule, e.runAtLocal)).subscribe({
      next: (res) => this.editDates.set(res.occurrences),
      error: (err) => this.editError.set(apiErrorMessage(err, 'Não foi possível calcular as datas.'))
    });
  }

  /** Mesmo canal, destinatários, variáveis e modelo; a versão lida evita sobrescrever a edição de outra pessoa. */
  saveEdit(): void {
    const e = this.editing();
    if (!e) return;
    const d = e.source;
    this.editError.set('');
    this.saving.set(true);
    this.api.updateSchedule(d.id, {
      name: e.name.trim(), channel: d.channel, subject: e.subject, body: e.body, priority: e.priority,
      variables: d.variables, template_id: d.template_id, recipient_ids: d.recipient_ids,
      ...ruleBodyOf(e.rule, e.runAtLocal), version: d.version
    }).subscribe({
      next: (saved) => {
        this.saving.set(false);
        this.editing.set(null);
        this.snack.open('Agendamento atualizado.', 'OK', { duration: 3000 });
        this.load();
        this.open(saved);
      },
      error: (err) => {
        this.saving.set(false);
        this.editError.set(apiErrorMessage(err, 'Não foi possível salvar.'));
      }
    });
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
