import { Component, OnInit, inject } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { RouterLink } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { MatTabsModule } from '@angular/material/tabs';

import { apiErrorMessage } from '../../../core/http/api-error';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';
import {
  SLA_PRIORITIES,
  SlaCalendar,
  SlaCalendarInput,
  SlaPolicy,
  SlaPolicyInput,
  SlaPriority,
  SlaService,
  formatMinutes
} from '../sla.service';

const WEEKDAYS = ['Segunda', 'Terça', 'Quarta', 'Quinta', 'Sexta', 'Sábado', 'Domingo'];
const REOPEN_LABELS: Record<string, string> = {
  RESTART: 'recomeça o prazo de resolução',
  CONTINUE: 'continua de onde parou'
};
const PAUSE_LABELS: Record<string, string> = { PENDING: 'Pendente', IN_PROGRESS: 'Em atendimento' };

interface TargetDraft {
  code: SlaPriority;
  label: string;
  enabled: boolean;
  firstHours: number | null;
  resolutionHours: number | null;
}

interface PolicyDraft {
  id?: string;
  name: string;
  description: string;
  calendar_id: string;
  is_active: boolean;
  alert_percent: number;
  reopen_rule: 'RESTART' | 'CONTINUE';
  pausePending: boolean;
  pauseInProgress: boolean;
  targets: TargetDraft[];
}

interface DayDraft {
  index: number;
  label: string;
  intervals: { start: string; end: string }[];
}

interface CalendarDraft {
  id?: string;
  name: string;
  timezone: string;
  days: DayDraft[];
  holidays: { day: string; name: string }[];
}

/** Horas (aceita fração: 0,5 = 30 min) -> minutos inteiros. */
function toMinutes(hours: number | null): number {
  return Math.round((Number(hours) || 0) * 60);
}

/**
 * Administração de SLA (ADR-017, P4-S4): políticas (prazos por prioridade) e calendários (expediente e feriados).
 * Mudanças valem só para chamados novos: cada chamado em andamento guardou a cópia da política quando começou.
 */
@Component({
  selector: 'app-sla-admin',
  standalone: true,
  imports: [
    FormsModule, RouterLink, LoadStateComponent, MatButtonModule, MatCheckboxModule, MatIconModule, MatInputModule,
    MatSelectModule, MatSlideToggleModule, MatSnackBarModule, MatTabsModule
  ],
  template: `
    <div class="page">
      <h1>SLA de chamados</h1>
      <p class="subtitle">
        Prazos de primeira resposta e de resolução, contados só no expediente do calendário. Para valer, a política
        precisa estar <strong>ativa</strong> e ligada a uma categoria em
        <a routerLink="/service-desk/categories">Categorias de Chamados</a>. Alterações valem para chamados novos.
      </p>

      <mat-tab-group animationDuration="0ms" mat-stretch-tabs="false">
        <mat-tab label="Políticas">
          <div class="tab">
            @if (policyDraft) {
              <form class="panel" data-testid="policy-form" (ngSubmit)="savePolicy()">
                <h2>{{ policyDraft.id ? 'Editar política' : 'Nova política' }}</h2>
                <div class="row">
                  <mat-form-field appearance="outline" class="grow">
                    <mat-label>Nome</mat-label>
                    <input matInput name="name" [(ngModel)]="policyDraft.name" required maxlength="100" data-testid="policy-name">
                  </mat-form-field>
                  <mat-form-field appearance="outline" class="grow">
                    <mat-label>Calendário (expediente)</mat-label>
                    <mat-select name="calendar" [(ngModel)]="policyDraft.calendar_id" required data-testid="policy-calendar">
                      @for (c of calendars; track c.id) { <mat-option [value]="c.id">{{ c.name }}</mat-option> }
                    </mat-select>
                  </mat-form-field>
                </div>
                <mat-form-field appearance="outline" class="full">
                  <mat-label>Descrição (opcional)</mat-label>
                  <input matInput name="description" [(ngModel)]="policyDraft.description" maxlength="2000">
                </mat-form-field>

                <h3>Prazos por prioridade <small>(horas úteis; 0,5 = 30 min)</small></h3>
                <table class="targets">
                  <thead><tr><th>Prioridade</th><th>Tem prazo</th><th>Primeira resposta</th><th>Resolução</th></tr></thead>
                  <tbody>
                    @for (t of policyDraft.targets; track t.code) {
                      <tr [attr.data-testid]="'target-' + t.code">
                        <td>{{ t.label }}</td>
                        <td><mat-checkbox [name]="'on-' + t.code" [(ngModel)]="t.enabled"></mat-checkbox></td>
                        <td>
                          <input class="hours" type="number" min="0" step="0.25" [name]="'first-' + t.code"
                                 [(ngModel)]="t.firstHours" [disabled]="!t.enabled" aria-label="Primeira resposta em horas">
                          @if (t.enabled && t.firstHours) { <span class="hint">{{ fmt(t.firstHours) }}</span> }
                        </td>
                        <td>
                          <input class="hours" type="number" min="0" step="0.25" [name]="'res-' + t.code"
                                 [(ngModel)]="t.resolutionHours" [disabled]="!t.enabled" aria-label="Resolução em horas">
                          @if (t.enabled && t.resolutionHours) { <span class="hint">{{ fmt(t.resolutionHours) }}</span> }
                        </td>
                      </tr>
                    }
                  </tbody>
                </table>
                <p class="note">Prioridade sem prazo: os chamados dela não têm relógio.</p>

                <h3>Comportamento</h3>
                <div class="row">
                  <mat-form-field appearance="outline">
                    <mat-label>Alerta de proximidade (%)</mat-label>
                    <input matInput type="number" min="0" max="99" name="alert" [(ngModel)]="policyDraft.alert_percent">
                    <mat-hint>Avisa ao passar deste ponto do prazo. 0 desliga.</mat-hint>
                  </mat-form-field>
                  <mat-form-field appearance="outline" class="grow">
                    <mat-label>Ao reabrir um chamado resolvido</mat-label>
                    <mat-select name="reopen" [(ngModel)]="policyDraft.reopen_rule">
                      <mat-option value="RESTART">Recomeçar o prazo de resolução</mat-option>
                      <mat-option value="CONTINUE">Continuar de onde parou</mat-option>
                    </mat-select>
                  </mat-form-field>
                </div>
                <div class="checks">
                  <span>O relógio para quando o chamado está:</span>
                  <mat-checkbox name="pausePending" [(ngModel)]="policyDraft.pausePending">Pendente</mat-checkbox>
                  <mat-checkbox name="pauseInProgress" [(ngModel)]="policyDraft.pauseInProgress">Em atendimento</mat-checkbox>
                </div>
                <mat-slide-toggle name="active" [(ngModel)]="policyDraft.is_active" data-testid="policy-active">
                  Política ativa (vale para chamados novos das categorias ligadas a ela)
                </mat-slide-toggle>

                @if (policyError) { <p class="error" role="alert">{{ policyError }}</p> }
                <div class="actions">
                  <button mat-stroked-button type="button" (click)="policyDraft = null">Cancelar</button>
                  <button mat-flat-button color="primary" type="submit" [disabled]="saving" data-testid="policy-save">
                    <mat-icon>save</mat-icon> Salvar
                  </button>
                </div>
              </form>
            } @else {
              <div class="toolbar">
                <button mat-flat-button color="primary" type="button" (click)="newPolicy()" [disabled]="!calendars.length" data-testid="policy-new">
                  <mat-icon>add</mat-icon> Nova política
                </button>
                @if (!loading && !calendars.length) { <span class="note">Crie um calendário antes.</span> }
              </div>
              <app-load-state [loading]="loading" [error]="loadError" [empty]="!policies.length"
                              emptyText="Nenhuma política de SLA." (retry)="load()">
                @for (p of policies; track p.id) {
                  <div class="card" [attr.data-testid]="'policy-' + p.name">
                    <div class="card-head">
                      <h2>{{ p.name }}</h2>
                      <span class="chip" [class.on]="p.is_active">{{ p.is_active ? 'Ativa' : 'Inativa' }}</span>
                    </div>
                    @if (p.description) { <p class="muted">{{ p.description }}</p> }
                    <p class="muted">
                      Calendário: {{ p.calendar_name }} · Alerta: {{ p.alert_percent ? p.alert_percent + '%' : 'desligado' }} ·
                      Reabertura: {{ reopenLabel(p.reopen_rule) }} · Pausa em: {{ pauseLabel(p.pause_statuses) }}
                    </p>
                    @if (p.targets.length) {
                      <table class="targets compact">
                        <thead><tr><th>Prioridade</th><th>Primeira resposta</th><th>Resolução</th></tr></thead>
                        <tbody>
                          @for (t of p.targets; track t.priority) {
                            <tr><td>{{ priorityLabel(t.priority) }}</td><td>{{ fmtMin(t.first_response_minutes) }}</td><td>{{ fmtMin(t.resolution_minutes) }}</td></tr>
                          }
                        </tbody>
                      </table>
                    } @else {
                      <p class="warn">Sem prazos: nenhum chamado terá relógio com esta política.</p>
                    }
                    <p class="muted">
                      Categorias: {{ p.category_names.length ? p.category_names.join(', ') : 'nenhuma (ligue em Categorias de Chamados)' }}
                    </p>
                    <div class="actions">
                      <button mat-stroked-button type="button" (click)="editPolicy(p)"><mat-icon>edit</mat-icon> Editar</button>
                      <button mat-stroked-button type="button" (click)="toggleActive(p)" [attr.data-testid]="'toggle-' + p.name">
                        <mat-icon>{{ p.is_active ? 'pause_circle' : 'play_circle' }}</mat-icon> {{ p.is_active ? 'Desativar' : 'Ativar' }}
                      </button>
                      <button mat-stroked-button color="warn" type="button" (click)="deletePolicy(p)"><mat-icon>delete</mat-icon> Excluir</button>
                    </div>
                  </div>
                }
              </app-load-state>
            }
          </div>
        </mat-tab>

        <mat-tab label="Calendários">
          <div class="tab">
            @if (calendarDraft) {
              <form class="panel" data-testid="calendar-form" (ngSubmit)="saveCalendar()">
                <h2>{{ calendarDraft.id ? 'Editar calendário' : 'Novo calendário' }}</h2>
                <div class="row">
                  <mat-form-field appearance="outline" class="grow">
                    <mat-label>Nome</mat-label>
                    <input matInput name="cname" [(ngModel)]="calendarDraft.name" required maxlength="100" data-testid="calendar-name">
                  </mat-form-field>
                  <mat-form-field appearance="outline" class="grow">
                    <mat-label>Fuso horário</mat-label>
                    <input matInput name="tz" [(ngModel)]="calendarDraft.timezone" required>
                    <mat-hint>Ex.: America/Sao_Paulo, America/Fortaleza</mat-hint>
                  </mat-form-field>
                </div>

                <h3>Expediente</h3>
                @for (d of calendarDraft.days; track d.index) {
                  <div class="day" [attr.data-testid]="'day-' + d.index">
                    <span class="day-label">{{ d.label }}</span>
                    @for (i of d.intervals; track $index) {
                      <span class="interval">
                        <input type="time" [name]="'s' + d.index + '-' + $index" [(ngModel)]="i.start" required aria-label="Início">
                        até
                        <input type="time" [name]="'e' + d.index + '-' + $index" [(ngModel)]="i.end" required aria-label="Fim">
                        <button mat-icon-button type="button" (click)="d.intervals.splice($index, 1)" aria-label="Remover intervalo">
                          <mat-icon>close</mat-icon>
                        </button>
                      </span>
                    } @empty {
                      <span class="muted">sem expediente</span>
                    }
                    <button mat-button type="button" (click)="addInterval(d)"><mat-icon>add</mat-icon> intervalo</button>
                  </div>
                }

                <h3>Feriados</h3>
                @for (h of calendarDraft.holidays; track $index) {
                  <div class="holiday">
                    <input type="date" [name]="'hd' + $index" [(ngModel)]="h.day" required aria-label="Data">
                    <input class="holiday-name" [name]="'hn' + $index" [(ngModel)]="h.name" required maxlength="100" placeholder="Nome" aria-label="Nome do feriado">
                    <button mat-icon-button type="button" (click)="calendarDraft.holidays.splice($index, 1)" aria-label="Remover feriado">
                      <mat-icon>close</mat-icon>
                    </button>
                  </div>
                } @empty {
                  <p class="muted">Nenhum feriado.</p>
                }
                <button mat-button type="button" (click)="calendarDraft.holidays.push({ day: '', name: '' })">
                  <mat-icon>add</mat-icon> feriado
                </button>

                @if (calendarError) { <p class="error" role="alert">{{ calendarError }}</p> }
                <div class="actions">
                  <button mat-stroked-button type="button" (click)="calendarDraft = null">Cancelar</button>
                  <button mat-flat-button color="primary" type="submit" [disabled]="saving" data-testid="calendar-save">
                    <mat-icon>save</mat-icon> Salvar
                  </button>
                </div>
              </form>
            } @else {
              <div class="toolbar">
                <button mat-flat-button color="primary" type="button" (click)="newCalendar()" data-testid="calendar-new">
                  <mat-icon>add</mat-icon> Novo calendário
                </button>
              </div>
              <app-load-state [loading]="loading" [error]="loadError" [empty]="!calendars.length"
                              emptyText="Nenhum calendário." (retry)="load()">
                @for (c of calendars; track c.id) {
                  <div class="card" [attr.data-testid]="'calendar-' + c.name">
                    <div class="card-head"><h2>{{ c.name }}</h2><span class="muted">{{ c.timezone }}</span></div>
                    <ul class="hours-list">
                      @for (line of hoursSummary(c); track $index) { <li>{{ line }}</li> }
                    </ul>
                    <p class="muted">
                      Feriados: {{ c.holidays.length ? holidaysSummary(c) : 'nenhum' }}
                    </p>
                    <p class="muted">Usado por: {{ c.policy_names.length ? c.policy_names.join(', ') : 'nenhuma política' }}</p>
                    <div class="actions">
                      <button mat-stroked-button type="button" (click)="editCalendar(c)"><mat-icon>edit</mat-icon> Editar</button>
                      <button mat-stroked-button color="warn" type="button" (click)="deleteCalendar(c)"><mat-icon>delete</mat-icon> Excluir</button>
                    </div>
                  </div>
                }
              </app-load-state>
            }
          </div>
        </mat-tab>
      </mat-tab-group>
    </div>
  `,
  styles: [`
    .page { max-width: 1100px; margin: 0 auto; padding: 24px 16px; }
    h1 { margin: 0; font-size: 24px; }
    .subtitle { margin: 4px 0 16px; color: #64748b; }
    .tab { padding-top: 12px; }
    .toolbar { display: flex; align-items: center; gap: 12px; margin-bottom: 12px; }
    .card, .panel { border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-bottom: 12px; background: #fff; }
    .card-head { display: flex; align-items: center; gap: 12px; }
    .card-head h2, .panel h2 { margin: 0; font-size: 18px; }
    .panel h3 { margin: 16px 0 8px; font-size: 15px; }
    .panel h3 small { font-weight: normal; color: #64748b; }
    .chip { font-size: 12px; padding: 2px 10px; border-radius: 12px; background: #f1f5f9; color: #475569; }
    .chip.on { background: #dcfce7; color: #166534; }
    .muted { color: #64748b; margin: 6px 0; font-size: 13px; }
    .warn { color: #b45309; font-size: 13px; }
    .note { color: #64748b; font-size: 12px; margin: 4px 0; }
    .error { color: #b91c1c; }
    .row { display: flex; gap: 12px; flex-wrap: wrap; }
    .grow { flex: 1 1 240px; }
    .full { width: 100%; }
    .targets { border-collapse: collapse; margin: 4px 0; }
    .targets th, .targets td { text-align: left; padding: 6px 12px 6px 0; font-size: 14px; }
    .targets.compact td, .targets.compact th { font-size: 13px; padding: 2px 16px 2px 0; }
    .hours { width: 90px; padding: 4px; }
    .hint { margin-left: 6px; color: #64748b; font-size: 12px; }
    .checks { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; margin: 8px 0 12px; }
    .actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 12px; flex-wrap: wrap; }
    .day { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; padding: 4px 0; }
    .day-label { width: 80px; font-weight: 500; }
    .interval { display: inline-flex; align-items: center; gap: 4px; }
    .holiday { display: flex; gap: 8px; align-items: center; margin: 4px 0; }
    .holiday-name { flex: 1; max-width: 320px; padding: 4px; }
    .hours-list { margin: 6px 0; padding-left: 18px; font-size: 13px; }
  `]
})
export class SlaAdminComponent implements OnInit {
  private sla = inject(SlaService);
  private snackBar = inject(MatSnackBar);

  policies: SlaPolicy[] = [];
  calendars: SlaCalendar[] = [];
  loading = true;
  loadError: string | null = null;
  saving = false;
  policyDraft: PolicyDraft | null = null;
  policyError: string | null = null;
  calendarDraft: CalendarDraft | null = null;
  calendarError: string | null = null;

  fmt = (hours: number) => formatMinutes(toMinutes(hours));
  fmtMin = formatMinutes;

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.loading = true;
    this.loadError = null;
    let pending = 2;
    const done = () => { if (--pending === 0) this.loading = false; };
    const fail = (err: unknown) => {
      this.loadError = apiErrorMessage(err, 'Não foi possível carregar o SLA.');
      done();
    };
    this.sla.listPolicies().subscribe({ next: (p) => { this.policies = p; done(); }, error: fail });
    this.sla.listCalendars().subscribe({ next: (c) => { this.calendars = c; done(); }, error: fail });
  }

  priorityLabel(code: string): string {
    return SLA_PRIORITIES.find((p) => p.code === code)?.label ?? code;
  }

  reopenLabel(rule: string): string {
    return REOPEN_LABELS[rule] ?? rule;
  }

  pauseLabel(statuses: string[]): string {
    return statuses.length ? statuses.map((s) => PAUSE_LABELS[s] ?? s).join(', ') : 'nunca';
  }

  hoursSummary(c: SlaCalendar): string[] {
    return WEEKDAYS.map((label, i) => {
      const intervals = c.weekly_hours[String(i)] ?? [];
      return `${label}: ${intervals.length ? intervals.map(([a, b]) => `${a}–${b}`).join(', ') : 'sem expediente'}`;
    });
  }

  holidaysSummary(c: SlaCalendar): string {
    return c.holidays.map((h) => `${h.day.split('-').reverse().join('/')} ${h.name}`).join('; ');
  }

  // ---------------------------------------------------------------- políticas

  newPolicy(): void {
    this.policyError = null;
    this.policyDraft = {
      name: '', description: '', calendar_id: this.calendars[0]?.id ?? '', is_active: false, alert_percent: 80,
      reopen_rule: 'RESTART', pausePending: true, pauseInProgress: false,
      targets: SLA_PRIORITIES.map((p) => ({ code: p.code, label: p.label, enabled: false, firstHours: null, resolutionHours: null }))
    };
  }

  editPolicy(p: SlaPolicy): void {
    this.policyError = null;
    this.policyDraft = {
      id: p.id, name: p.name, description: p.description ?? '', calendar_id: p.calendar_id, is_active: p.is_active,
      alert_percent: p.alert_percent, reopen_rule: p.reopen_rule,
      pausePending: p.pause_statuses.includes('PENDING'), pauseInProgress: p.pause_statuses.includes('IN_PROGRESS'),
      targets: SLA_PRIORITIES.map((pr) => {
        const t = p.targets.find((x) => x.priority === pr.code);
        return {
          code: pr.code, label: pr.label, enabled: !!t,
          firstHours: t ? t.first_response_minutes / 60 : null, resolutionHours: t ? t.resolution_minutes / 60 : null
        };
      })
    };
  }

  /** Monta o corpo da API e devolve o erro de preenchimento, se houver. */
  private policyPayload(d: PolicyDraft): SlaPolicyInput | string {
    if (!d.name.trim()) return 'Informe o nome da política.';
    if (!d.calendar_id) return 'Escolha um calendário.';
    const targets = [];
    for (const t of d.targets.filter((x) => x.enabled)) {
      const first = toMinutes(t.firstHours);
      const resolution = toMinutes(t.resolutionHours);
      if (first < 1 || resolution < 1) return `Prioridade ${t.label}: informe os dois prazos.`;
      if (resolution < first) return `Prioridade ${t.label}: a resolução não pode ser menor que a primeira resposta.`;
      targets.push({ priority: t.code, first_response_minutes: first, resolution_minutes: resolution });
    }
    const pause = [...(d.pauseInProgress ? ['IN_PROGRESS'] : []), ...(d.pausePending ? ['PENDING'] : [])];
    return {
      name: d.name.trim(), description: d.description.trim() || null, calendar_id: d.calendar_id, is_active: d.is_active,
      alert_percent: Number(d.alert_percent) || 0, reopen_rule: d.reopen_rule, pause_statuses: pause, targets
    };
  }

  savePolicy(): void {
    const d = this.policyDraft;
    if (!d) return;
    const payload = this.policyPayload(d);
    if (typeof payload === 'string') {
      this.policyError = payload;
      return;
    }
    this.saving = true;
    const call = d.id ? this.sla.updatePolicy(d.id, payload) : this.sla.createPolicy(payload);
    call.subscribe({
      next: () => {
        this.saving = false;
        this.policyDraft = null;
        this.snackBar.open('Política salva.', 'OK', { duration: 3000 });
        this.load();
      },
      error: (err) => {
        this.saving = false;
        this.policyError = apiErrorMessage(err, 'Não foi possível salvar a política.');
      }
    });
  }

  toggleActive(p: SlaPolicy): void {
    this.sla.updatePolicy(p.id, { is_active: !p.is_active }).subscribe({
      next: () => {
        this.snackBar.open(p.is_active ? 'Política desativada.' : 'Política ativada.', 'OK', { duration: 3000 });
        this.load();
      },
      error: (err) => this.snackBar.open(apiErrorMessage(err, 'Não foi possível alterar a política.'), 'Fechar', { duration: 5000 })
    });
  }

  deletePolicy(p: SlaPolicy): void {
    if (!confirm(`Excluir a política "${p.name}"? Chamados em andamento mantêm os prazos que já tinham.`)) return;
    this.sla.deletePolicy(p.id).subscribe({
      next: () => { this.snackBar.open('Política excluída.', 'OK', { duration: 3000 }); this.load(); },
      error: (err) => this.snackBar.open(apiErrorMessage(err, 'Não foi possível excluir a política.'), 'Fechar', { duration: 6000 })
    });
  }

  // ---------------------------------------------------------------- calendários

  newCalendar(): void {
    this.calendarError = null;
    this.calendarDraft = {
      name: '', timezone: 'America/Sao_Paulo', holidays: [],
      days: WEEKDAYS.map((label, index) => ({ index, label, intervals: index < 5 ? [{ start: '08:00', end: '18:00' }] : [] }))
    };
  }

  editCalendar(c: SlaCalendar): void {
    this.calendarError = null;
    this.calendarDraft = {
      id: c.id, name: c.name, timezone: c.timezone, holidays: c.holidays.map((h) => ({ ...h })),
      days: WEEKDAYS.map((label, index) => ({
        index, label, intervals: (c.weekly_hours[String(index)] ?? []).map(([start, end]) => ({ start, end }))
      }))
    };
  }

  addInterval(d: DayDraft): void {
    const last = d.intervals[d.intervals.length - 1];
    d.intervals.push(last ? { start: last.end, end: '18:00' } : { start: '08:00', end: '18:00' });
  }

  saveCalendar(): void {
    const d = this.calendarDraft;
    if (!d) return;
    if (!d.name.trim()) {
      this.calendarError = 'Informe o nome do calendário.';
      return;
    }
    if (d.holidays.some((h) => !h.day || !h.name.trim())) {
      this.calendarError = 'Cada feriado precisa de data e nome.';
      return;
    }
    const weekly: Record<string, string[][]> = {};
    for (const day of d.days) {
      if (day.intervals.length) weekly[String(day.index)] = day.intervals.map((i) => [i.start, i.end]);
    }
    const payload: SlaCalendarInput = {
      name: d.name.trim(), timezone: d.timezone.trim(), weekly_hours: weekly,
      holidays: d.holidays.map((h) => ({ day: h.day, name: h.name.trim() }))
    };
    this.saving = true;
    const call = d.id ? this.sla.updateCalendar(d.id, payload) : this.sla.createCalendar(payload);
    call.subscribe({
      next: () => {
        this.saving = false;
        this.calendarDraft = null;
        this.snackBar.open('Calendário salvo.', 'OK', { duration: 3000 });
        this.load();
      },
      error: (err) => {
        this.saving = false;
        this.calendarError = apiErrorMessage(err, 'Não foi possível salvar o calendário.');
      }
    });
  }

  deleteCalendar(c: SlaCalendar): void {
    if (!confirm(`Excluir o calendário "${c.name}"?`)) return;
    this.sla.deleteCalendar(c.id).subscribe({
      next: () => { this.snackBar.open('Calendário excluído.', 'OK', { duration: 3000 }); this.load(); },
      error: (err) => this.snackBar.open(apiErrorMessage(err, 'Não foi possível excluir o calendário.'), 'Fechar', { duration: 6000 })
    });
  }
}
