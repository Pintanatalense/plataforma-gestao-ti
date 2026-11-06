import { apiErrorMessage } from '../../../core/http/api-error';
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
  RuleEscalation,
  RuleInput,
  RuleItem,
  RulesResponse,
  SimulatedDelivery
} from '../../../core/services/notifications-admin.service';

/** Texto digitado (separado por vírgula ou quebra de linha) -> lista limpa e sem repetições. */
export function parseList(text: string): string[] {
  return [...new Set(text.split(/[\n,]/).map((s) => s.trim()).filter(Boolean))];
}

export { apiErrorMessage };

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
  escalate: boolean;
  escalation_minutes: number;
  escalation_until: 'first_response' | 'resolved';
  escalation_audienceText: string;
  escalation_channels: string[];
  fallback_channel: string | null;
}

const EMPTY_FORM: RuleForm = {
  id: null, isSystem: false, name: '', enabled: true, event_type: '', audienceText: '',
  channels: ['in_app'], template_code: 'generic', min_priority: '', exclude_actor: true,
  escalate: false, escalation_minutes: 60, escalation_until: 'first_response', escalation_audienceText: 'admins',
  escalation_channels: [], fallback_channel: null
};

/** Campos que a API recebe, sem perder escalonamento e canal alternativo de quem só liga ou desliga a regra. */
export function ruleInputOf(r: RuleItem, enabled = r.enabled): RuleInput {
  return {
    name: r.name, enabled, event_type: r.event_type, condition: r.condition, audience: r.audience,
    channels: r.channels, template_code: r.template_code, escalation: r.escalation ?? {},
    fallback_channel: r.fallback_channel ?? null
  };
}

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
              <td>
                {{ eventLabel(r.event_type) }}
                @if (!r.in_catalog) { <span class="chip warn" title="Evento fora do catálogo: confira se ele existe">fora do catálogo</span> }
                @if (r.escalation?.after_minutes) { <span class="chip" data-testid="rule-escalation">escalona em {{ r.escalation.after_minutes }} min</span> }
              </td>
              <td>{{ r.audience.join(', ') }}</td>
              <td>{{ r.channels.join(', ') }}{{ r.fallback_channel ? ' · se falhar: ' + r.fallback_channel : '' }}</td>
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
          <mat-label>Evento</mat-label>
          <mat-select [(ngModel)]="f.event_type" name="event_type" data-testid="rule-event">
            @for (e of options()?.events ?? []; track e.code) {
              <mat-option [value]="e.code">{{ e.area }} · {{ e.label }}</mat-option>
            }
            @if (f.event_type && !isCatalogEvent(f.event_type)) {
              <mat-option [value]="f.event_type">{{ f.event_type }} (fora do catálogo)</mat-option>
            }
          </mat-select>
          <mat-hint>{{ f.event_type }}</mat-hint>
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
        <mat-form-field appearance="outline">
          <mat-label>Se a entrega falhar de vez, tentar por</mat-label>
          <mat-select [(ngModel)]="f.fallback_channel" name="fallback" data-testid="rule-fallback">
            <mat-option [value]="null">Nenhum outro canal</mat-option>
            @for (c of fallbackChannels(); track c) { <mat-option [value]="c">{{ c }}</mat-option> }
          </mat-select>
          <mat-hint>Uma tentativa a mais, por outro canal, para quem ainda não recebeu este aviso por ele.</mat-hint>
        </mat-form-field>
        @if (acceptsEscalation(f.event_type)) {
          <mat-checkbox [(ngModel)]="f.escalate" name="escalate" data-testid="rule-escalate">Escalonar se ninguém agir</mat-checkbox>
          @if (f.escalate) {
            <div class="sim-row" data-testid="rule-escalation-form">
              <mat-form-field appearance="outline">
                <mat-label>Depois de (minutos)</mat-label>
                <input matInput type="number" min="5" max="10080" [(ngModel)]="f.escalation_minutes" name="esc_minutes" />
              </mat-form-field>
              <mat-form-field appearance="outline">
                <mat-label>Escalonar</mat-label>
                <mat-select [(ngModel)]="f.escalation_until" name="esc_until">
                  @for (u of untilOptions(); track u.key) { <mat-option [value]="u.key">{{ u.label }}</mat-option> }
                </mat-select>
              </mat-form-field>
            </div>
            <mat-form-field appearance="outline">
              <mat-label>Escalonar para (separe por vírgula)</mat-label>
              <input matInput [(ngModel)]="f.escalation_audienceText" name="esc_audience" />
              <mat-hint>Ex.: admins, role:Gestão. A condição é conferida na hora: se já resolveram, não sai.</mat-hint>
            </mat-form-field>
            <div class="checks">
              <span>Canais do escalonamento (vazio = os mesmos da regra):</span>
              @for (c of options()?.channels ?? []; track c) {
                <mat-checkbox [checked]="f.escalation_channels.includes(c)" (change)="setEscalationChannel(f, c, $event.checked)">{{ c }}</mat-checkbox>
              }
            </div>
          }
        }
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
            <li><strong>{{ d.recipient_email }}</strong> — {{ d.channel }} — "{{ d.title }}" ({{ d.rule }}) · envio {{ d.send_at | date: 'dd/MM HH:mm' }}{{ d.escalation_until ? ' · escalonamento, se ainda valer' : '' }}</li>
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
    .chip { padding: 1px 8px; border-radius: 12px; font-size: 11px; background: #e2e8f0; margin-left: 4px; }
    .chip.warn { background: #fef3c7; color: #92400e; }
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
    const esc = r.escalation as Partial<RuleEscalation>;
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
      exclude_actor: condition.exclude_actor ?? true,
      escalate: !!esc.after_minutes,
      escalation_minutes: esc.after_minutes ?? EMPTY_FORM.escalation_minutes,
      escalation_until: esc.until ?? 'first_response',
      escalation_audienceText: (esc.audience ?? ['admins']).join(', '),
      escalation_channels: [...(esc.channels ?? [])],
      fallback_channel: r.fallback_channel ?? null
    });
  }

  setChannel(f: RuleForm, channel: string, checked: boolean): void {
    f.channels = checked ? [...new Set([...f.channels, channel])] : f.channels.filter((c) => c !== channel);
  }

  setEscalationChannel(f: RuleForm, channel: string, checked: boolean): void {
    f.escalation_channels = checked
      ? [...new Set([...f.escalation_channels, channel])]
      : f.escalation_channels.filter((c) => c !== channel);
  }

  isCatalogEvent(code: string): boolean {
    return (this.options()?.events ?? []).some((e) => e.code === code);
  }

  eventLabel(code: string): string {
    return (this.options()?.events ?? []).find((e) => e.code === code)?.label ?? code;
  }

  acceptsEscalation(code: string): boolean {
    return code === 'ticket.*' || !!(this.options()?.events ?? []).find((e) => e.code === code)?.escalation;
  }

  untilOptions(): { key: string; label: string }[] {
    return Object.entries(this.options()?.escalation_until ?? {}).map(([key, label]) => ({ key, label }));
  }

  fallbackChannels(): string[] {
    return (this.options()?.channels ?? []).filter((c) => c !== 'preferred');
  }

  private toInput(f: RuleForm, base?: RuleItem): RuleInput {
    const condition: Record<string, unknown> = { ...(base?.condition ?? {}) };
    delete condition['min_priority'];
    delete condition['exclude_actor'];
    if (f.min_priority) condition['min_priority'] = f.min_priority;
    if (!f.exclude_actor) condition['exclude_actor'] = false;
    const escalate = f.escalate && this.acceptsEscalation(f.event_type);
    const escalation: RuleEscalation | Record<string, never> = escalate
      ? {
          after_minutes: Number(f.escalation_minutes),
          until: f.escalation_until,
          audience: parseList(f.escalation_audienceText),
          ...(f.escalation_channels.length ? { channels: f.escalation_channels } : {})
        }
      : {};
    return {
      name: f.name.trim(),
      enabled: f.enabled,
      event_type: f.event_type.trim(),
      condition,
      audience: parseList(f.audienceText),
      channels: f.channels,
      template_code: f.template_code,
      escalation,
      fallback_channel: f.fallback_channel
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
    this.api.updateRule(r.id, ruleInputOf(r, enabled)).subscribe({
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
