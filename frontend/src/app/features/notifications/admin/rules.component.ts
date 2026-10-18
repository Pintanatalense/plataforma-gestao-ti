import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule, DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatInputModule } from '@angular/material/input';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import {
  NotificationsAdminService,
  RuleInput,
  RuleItem,
  RulesResponse,
  SimulatedDelivery
} from '../../../core/services/notifications-admin.service';

/** Texto digitado (separado por vírgula ou quebra de linha) -> lista limpa e sem repetições. */
export function parseList(text: string): string[] {
  return [...new Set(text.split(/[\n,]/).map((s) => s.trim()).filter(Boolean))];
}

/** Extrai a mensagem de erro da API (VALIDATION_ERROR ou regra de negócio). */
export function apiErrorMessage(err: any, fallback: string): string {
  const e = err?.error?.error;
  if (!e) return fallback;
  if (Array.isArray(e.details) && e.details.length) {
    return e.details.map((d: any) => (typeof d.msg === 'string' ? d.msg.replace(/^Value error, /, '') : '')).filter(Boolean).join(' ');
  }
  return e.message ?? fallback;
}

interface RuleForm {
  id: string | null;
  isSystem: boolean;
  name: string;
  enabled: boolean;
  event_type: string;
  audienceText: string;
  channels: string[];
  template_code: string;
  min_priority: string;
  exclude_actor: boolean;
}

const EMPTY_FORM: RuleForm = {
  id: null, isSystem: false, name: '', enabled: true, event_type: '', audienceText: '',
  channels: ['in_app'], template_code: 'generic', min_priority: '', exclude_actor: true
};

@Component({
  selector: 'app-rules',
  standalone: true,
  imports: [
    CommonModule, FormsModule, DatePipe,
    MatButtonModule, MatIconModule, MatFormFieldModule, MatSelectModule, MatInputModule,
    MatSlideToggleModule, MatCheckboxModule, MatSnackBarModule
  ],
  template: `
    <div class="bar">
      <button mat-flat-button color="primary" (click)="startNew()" data-testid="new-rule"><mat-icon>add</mat-icon> Nova regra</button>
    </div>

    <div class="table-wrap">
      <table class="grid" data-testid="rules-table">
        <thead><tr><th>Ativa</th><th>Regra</th><th>Evento</th><th>Quem recebe</th><th>Canais</th><th></th></tr></thead>
        <tbody>
          @for (r of rules(); track r.id) {
            <tr data-testid="rule-row">
              <td><mat-slide-toggle [checked]="r.enabled" (change)="toggle(r, $event.checked)" aria-label="Ativar regra" /></td>
              <td>{{ r.name }} @if (r.is_system) { <span class="chip">padrão</span> }</td>
              <td><code>{{ r.event_type }}</code></td>
              <td>{{ r.audience.join(', ') }}</td>
              <td>{{ r.channels.join(', ') }}</td>
              <td class="row-actions">
                <button mat-icon-button (click)="edit(r)" aria-label="Editar"><mat-icon>edit</mat-icon></button>
                @if (!r.is_system) {
                  <button mat-icon-button (click)="remove(r)" aria-label="Excluir"><mat-icon>delete</mat-icon></button>
                }
              </td>
            </tr>
          }
        </tbody>
      </table>
    </div>

    @if (form(); as f) {
      <section class="card" data-testid="rule-form">
        <h3>{{ f.id ? 'Editar regra' : 'Nova regra' }}</h3>
        <mat-form-field appearance="outline">
          <mat-label>Nome</mat-label>
          <input matInput [(ngModel)]="f.name" name="name" />
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Evento (ex.: ticket.created ou ticket.*)</mat-label>
          <input matInput [(ngModel)]="f.event_type" name="event_type" />
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Quem recebe (separe por vírgula)</mat-label>
          <textarea matInput rows="2" [(ngModel)]="f.audienceText" name="audience"></textarea>
          <mat-hint>Opções: {{ options()?.selectors?.join(', ') }}</mat-hint>
        </mat-form-field>
        <div class="checks">
          <span>Canais:</span>
          @for (c of options()?.channels ?? []; track c) {
            <mat-checkbox [checked]="f.channels.includes(c)" (change)="setChannel(f, c, $event.checked)">{{ c }}</mat-checkbox>
          }
        </div>
        <mat-form-field appearance="outline">
          <mat-label>Modelo da mensagem</mat-label>
          <mat-select [(ngModel)]="f.template_code" name="template">
            @for (t of options()?.templates ?? []; track t) {
              <mat-option [value]="t">{{ t }}</mat-option>
            }
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Prioridade mínima</mat-label>
          <mat-select [(ngModel)]="f.min_priority" name="min_priority">
            <mat-option value="">Qualquer</mat-option>
            <mat-option value="normal">Normal ou mais</mat-option>
            <mat-option value="high">Alta ou mais</mat-option>
            <mat-option value="critical">Crítica</mat-option>
          </mat-select>
        </mat-form-field>
        <mat-checkbox [(ngModel)]="f.exclude_actor" name="exclude_actor">Não avisar quem causou o evento</mat-checkbox>
        <mat-slide-toggle [(ngModel)]="f.enabled" name="enabled">Regra ativa</mat-slide-toggle>
        @if (error()) {
          <p class="error" role="alert">{{ error() }}</p>
        }
        <div class="footer">
          <button mat-button (click)="form.set(null)">Cancelar</button>
          <button mat-flat-button color="primary" (click)="save()" data-testid="save-rule">Salvar</button>
        </div>
      </section>
    }

    <section class="card">
      <h3>Simulador</h3>
      <p class="hint">Descubra quem receberia o quê se um evento ocorresse agora. Nada é enviado nem gravado.</p>
      <div class="sim-row">
        <mat-form-field appearance="outline">
          <mat-label>Evento</mat-label>
          <input matInput [(ngModel)]="simEvent" name="sim_event" data-testid="sim-event" />
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Prioridade</mat-label>
          <mat-select [(ngModel)]="simPriority" name="sim_priority">
            <mat-option value="low">Baixa</mat-option>
            <mat-option value="normal">Normal</mat-option>
            <mat-option value="high">Alta</mat-option>
            <mat-option value="critical">Crítica</mat-option>
          </mat-select>
        </mat-form-field>
      </div>
      <mat-form-field appearance="outline">
        <mat-label>Dados do evento (JSON)</mat-label>
        <textarea matInput rows="3" [(ngModel)]="simPayload" name="sim_payload"></textarea>
        <mat-hint>Ex.: {{ '{' }}"requester_employee_id": "...", "responsible_sector_id": "..."{{ '}' }}</mat-hint>
      </mat-form-field>
      <div class="footer"><button mat-stroked-button (click)="simulate()" data-testid="simulate">Simular</button></div>
      @if (simError()) {
        <p class="error" role="alert">{{ simError() }}</p>
      }
      @if (simulated(); as sim) {
        <ul data-testid="sim-result">
          @for (d of sim; track $index) {
            <li><strong>{{ d.recipient_email }}</strong> — {{ d.channel }} — "{{ d.title }}" ({{ d.rule }}) · envio {{ d.send_at | date: 'dd/MM HH:mm' }}</li>
          } @empty {
            <li>Nenhuma regra ativa entregaria este evento a alguém.</li>
          }
        </ul>
      }
    </section>
  `,
  styles: [`
    .bar { margin: 16px 0 8px; }
    .table-wrap { overflow-x: auto; }
    .grid { width: 100%; border-collapse: collapse; font-size: 13px; }
    .grid th { text-align: left; padding: 8px; border-bottom: 2px solid #e2e8f0; color: #475569; }
    .grid td { padding: 8px; border-bottom: 1px solid #f1f5f9; vertical-align: middle; }
    .chip { padding: 1px 8px; border-radius: 12px; font-size: 11px; background: #e2e8f0; }
    .row-actions { white-space: nowrap; text-align: right; }
    .card { display: flex; flex-direction: column; gap: 8px; border: 1px solid #e2e8f0; border-radius: 8px; padding: 16px; margin-top: 16px; background: #fff; }
    .card h3 { margin: 0; }
    .checks { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; }
    .sim-row { display: flex; gap: 12px; flex-wrap: wrap; }
    .sim-row mat-form-field { flex: 1 1 180px; }
    .footer { display: flex; justify-content: flex-end; gap: 8px; }
    .hint { color: #64748b; margin: 0; font-size: 13px; }
    .error { color: #dc2626; margin: 0; }
  `]
})
export class RulesComponent implements OnInit {
  private api = inject(NotificationsAdminService);
  private snack = inject(MatSnackBar);

  rules = signal<RuleItem[]>([]);
  options = signal<RulesResponse['options'] | null>(null);
  form = signal<RuleForm | null>(null);
  error = signal('');

  simEvent = 'ticket.created';
  simPriority = 'normal';
  simPayload = '{}';
  simulated = signal<SimulatedDelivery[] | null>(null);
  simError = signal('');

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.api.listRules().subscribe({
      next: (res) => {
        this.rules.set(res.items);
        this.options.set(res.options);
      },
      error: () => this.snack.open('Não foi possível carregar as regras.', 'OK', { duration: 4000 })
    });
  }

  startNew(): void {
    this.error.set('');
    this.form.set({ ...EMPTY_FORM, channels: [...EMPTY_FORM.channels] });
  }

  edit(r: RuleItem): void {
    this.error.set('');
    const condition = r.condition as { min_priority?: string; exclude_actor?: boolean };
    this.form.set({
      id: r.id,
      isSystem: r.is_system,
      name: r.name,
      enabled: r.enabled,
      event_type: r.event_type,
      audienceText: r.audience.join(', '),
      channels: [...r.channels],
      template_code: r.template_code,
      min_priority: condition.min_priority ?? '',
      exclude_actor: condition.exclude_actor ?? true
    });
  }

  setChannel(f: RuleForm, channel: string, checked: boolean): void {
    f.channels = checked ? [...new Set([...f.channels, channel])] : f.channels.filter((c) => c !== channel);
  }

  private toInput(f: RuleForm, base?: RuleItem): RuleInput {
    const condition: Record<string, unknown> = { ...(base?.condition ?? {}) };
    delete condition['min_priority'];
    delete condition['exclude_actor'];
    if (f.min_priority) condition['min_priority'] = f.min_priority;
    if (!f.exclude_actor) condition['exclude_actor'] = false;
    return {
      name: f.name.trim(),
      enabled: f.enabled,
      event_type: f.event_type.trim(),
      condition,
      audience: parseList(f.audienceText),
      channels: f.channels,
      template_code: f.template_code
    };
  }

  save(): void {
    const f = this.form();
    if (!f) return;
    const base = this.rules().find((r) => r.id === f.id);
    const body = this.toInput(f, base);
    const request = f.id ? this.api.updateRule(f.id, body) : this.api.createRule(body);
    request.subscribe({
      next: () => {
        this.form.set(null);
        this.snack.open('Regra salva.', 'OK', { duration: 3000 });
        this.load();
      },
      error: (err) => this.error.set(apiErrorMessage(err, 'Não foi possível salvar a regra.'))
    });
  }

  toggle(r: RuleItem, enabled: boolean): void {
    const body: RuleInput = {
      name: r.name, enabled, event_type: r.event_type, condition: r.condition,
      audience: r.audience, channels: r.channels, template_code: r.template_code
    };
    this.api.updateRule(r.id, body).subscribe({
      next: () => this.load(),
      error: () => {
        this.snack.open('Não foi possível alterar a regra.', 'OK', { duration: 4000 });
        this.load();
      }
    });
  }

  remove(r: RuleItem): void {
    if (!confirm(`Excluir a regra "${r.name}"?`)) return;
    this.api.deleteRule(r.id).subscribe({
      next: () => this.load(),
      error: (err) => this.snack.open(apiErrorMessage(err, 'Não foi possível excluir.'), 'OK', { duration: 4000 })
    });
  }

  simulate(): void {
    this.simError.set('');
    let payload: Record<string, unknown>;
    try {
      payload = JSON.parse(this.simPayload || '{}');
    } catch {
      this.simError.set('Os dados do evento não são um JSON válido.');
      return;
    }
    this.api.simulate({ event_type: this.simEvent.trim(), priority: this.simPriority, payload }).subscribe({
      next: (res) => this.simulated.set(res.deliveries),
      error: (err) => this.simError.set(apiErrorMessage(err, 'Não foi possível simular.'))
    });
  }
}
