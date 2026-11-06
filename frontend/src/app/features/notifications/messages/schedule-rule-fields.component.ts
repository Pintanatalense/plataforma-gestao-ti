import { Component, EventEmitter, Input, Output, model } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { BusinessCalendarOption, ScheduleRule } from '../../../core/services/messages.service';

export const WEEKDAY_NAMES = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];

export function emptyRule(): ScheduleRule {
  return {
    recurrence: 'once', run_at: null, time_of_day: '09:00', weekdays: [], month_day: 1, starts_on: null, ends_on: null,
    calendar_id: null, non_business_rule: 'skip'
  };
}

export function toggleWeekday(rule: ScheduleRule, day: number): void {
  const days = rule.weekdays;
  rule.weekdays = days.includes(day) ? days.filter((d) => d !== day) : [...days, day].sort();
}

/** O que vai para a API: só os campos do tipo de repetição escolhido; data e hora únicas com fuso (ISO). */
export function ruleBodyOf(rule: ScheduleRule, runAtLocal: string): ScheduleRule {
  const once = rule.recurrence === 'once';
  return {
    ...rule,
    run_at: once && runAtLocal ? new Date(runAtLocal).toISOString() : null,
    time_of_day: once ? null : rule.time_of_day,
    starts_on: once ? null : rule.starts_on || null,
    ends_on: once ? null : rule.ends_on || null,
    calendar_id: once ? null : rule.calendar_id
  };
}

/** Instante ISO (UTC) no formato do campo `datetime-local`, no fuso do navegador. */
export function toLocalInput(iso: string | null): string {
  if (!iso) return '';
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** Campos da regra de agendamento, usados ao criar (Nova mensagem) e ao editar (Agendamentos). */
@Component({
  selector: 'app-schedule-rule-fields',
  standalone: true,
  imports: [FormsModule, MatFormFieldModule, MatInputModule, MatSelectModule],
  template: `
    <div class="row">
      <mat-form-field appearance="outline">
        <mat-label>Repetição</mat-label>
        <mat-select [(ngModel)]="rule.recurrence" (selectionChange)="changed.emit()" data-testid="m-recurrence">
          <mat-option value="once">Uma vez</mat-option>
          <mat-option value="daily">Todo dia</mat-option>
          <mat-option value="weekly">Dias da semana</mat-option>
          <mat-option value="monthly">Todo mês</mat-option>
        </mat-select>
      </mat-form-field>
      @if (rule.recurrence === 'once') {
        <mat-form-field appearance="outline">
          <mat-label>Data e hora</mat-label>
          <input matInput type="datetime-local" [ngModel]="runAt()" (ngModelChange)="runAt.set($event); changed.emit()" data-testid="m-run-at" />
        </mat-form-field>
      } @else {
        <mat-form-field appearance="outline">
          <mat-label>Horário</mat-label>
          <input matInput type="time" [(ngModel)]="rule.time_of_day" (ngModelChange)="changed.emit()" data-testid="m-time" />
        </mat-form-field>
        @if (rule.recurrence === 'monthly') {
          <mat-form-field appearance="outline">
            <mat-label>Dia do mês</mat-label>
            <input matInput type="number" min="1" max="31" [(ngModel)]="rule.month_day" (ngModelChange)="changed.emit()" />
            <mat-hint>Em mês mais curto, vai no último dia.</mat-hint>
          </mat-form-field>
        }
        <mat-form-field appearance="outline">
          <mat-label>A partir de</mat-label>
          <input matInput type="date" [(ngModel)]="rule.starts_on" (ngModelChange)="changed.emit()" />
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Até (opcional)</mat-label>
          <input matInput type="date" [(ngModel)]="rule.ends_on" (ngModelChange)="changed.emit()" />
        </mat-form-field>
      }
    </div>
    @if (rule.recurrence === 'weekly') {
      <div class="weekdays">
        @for (label of weekdayNames; track $index) {
          <label><input type="checkbox" [checked]="rule.weekdays.includes($index)" (change)="toggle($index)"
            [attr.data-testid]="'m-weekday-' + $index" /> {{ label }}</label>
        }
      </div>
    }
    @if (rule.recurrence !== 'once') {
      <div class="row">
        <mat-form-field appearance="outline">
          <mat-label>Dias úteis (calendário do SLA)</mat-label>
          <mat-select [(ngModel)]="rule.calendar_id" (selectionChange)="changed.emit()" data-testid="m-calendar">
            <mat-option [value]="null">Todos os dias</mat-option>
            @for (c of calendars; track c.id) {
              <mat-option [value]="c.id">{{ c.name }}</mat-option>
            }
          </mat-select>
        </mat-form-field>
        @if (rule.calendar_id) {
          <mat-form-field appearance="outline">
            <mat-label>Em feriado ou dia sem expediente</mat-label>
            <mat-select [(ngModel)]="rule.non_business_rule" (selectionChange)="changed.emit()">
              <mat-option value="skip">Não enviar</mat-option>
              <mat-option value="next">Enviar no próximo dia útil</mat-option>
            </mat-select>
          </mat-form-field>
        }
      </div>
    }
  `,
  styles: [`
    .row { display: flex; flex-wrap: wrap; gap: 12px; }
    .row mat-form-field { flex: 1 1 180px; }
    .weekdays { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 12px; }
  `]
})
export class ScheduleRuleFieldsComponent {
  @Input({ required: true }) rule!: ScheduleRule;
  @Input() calendars: BusinessCalendarOption[] = [];
  @Output() changed = new EventEmitter<void>();
  /** Data e hora do envio único, no formato do campo `datetime-local`. */
  runAt = model('');
  readonly weekdayNames = WEEKDAY_NAMES;

  toggle(day: number): void {
    toggleWeekday(this.rule, day);
    this.changed.emit();
  }
}
