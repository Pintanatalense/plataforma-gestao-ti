import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { Observable } from 'rxjs';
import { apiErrorMessage } from '../../../core/http/api-error';
import {
  MessageDraft,
  MessageTemplate,
  MessagesService,
  PreviewResponse,
  RecipientOption
} from '../../../core/services/messages.service';
import { CHANNEL_NAMES } from '../admin/channels.component';

export const OUTCOME_LABELS: Record<string, string> = {
  queued: 'Vai receber',
  no_address: 'Não vinculou este canal',
  out_of_scope: 'Fora do seu setor',
  inactive: 'Conta inativa',
  unknown: 'Conta não encontrada'
};

const PLACEHOLDER = /\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g;

/** Variáveis usadas no texto que a pessoa precisa preencher (as do sistema são preenchidas sozinhas). */
export function customVariables(texts: string[], builtin: string[]): string[] {
  const found = new Set<string>();
  for (const text of texts) {
    for (const match of (text ?? '').matchAll(PLACEHOLDER)) found.add(match[1].toLowerCase());
  }
  return [...found].filter((name) => !builtin.includes(name)).sort();
}

function newKey(): string {
  return crypto.randomUUID();
}

@Component({
  selector: 'app-message-compose',
  standalone: true,
  imports: [FormsModule, MatButtonModule, MatFormFieldModule, MatIconModule, MatInputModule, MatSelectModule, MatSnackBarModule],
  template: `
    <section class="form">
      <div class="row">
        <mat-form-field appearance="outline">
          <mat-label>Canal</mat-label>
          <mat-select [(ngModel)]="draft.channel" (selectionChange)="changed()" data-testid="m-channel">
            @for (c of channels; track c.key) {
              <mat-option [value]="c.key">{{ c.label }}</mat-option>
            }
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Modelo</mat-label>
          <mat-select [(ngModel)]="draft.template_id" (selectionChange)="applyTemplate()" data-testid="m-template">
            <mat-option [value]="null">Sem modelo</mat-option>
            @for (t of templatesFor(); track t.id) {
              <mat-option [value]="t.id">{{ t.name }}</mat-option>
            }
          </mat-select>
        </mat-form-field>
        <mat-form-field appearance="outline">
          <mat-label>Prioridade</mat-label>
          <mat-select [(ngModel)]="draft.priority" (selectionChange)="changed()">
            <mat-option value="low">Baixa</mat-option>
            <mat-option value="normal">Normal</mat-option>
            <mat-option value="high">Alta</mat-option>
          </mat-select>
        </mat-form-field>
      </div>

      <mat-form-field appearance="outline" class="full">
        <mat-label>Assunto</mat-label>
        <input matInput [(ngModel)]="draft.subject" (ngModelChange)="changed()" maxlength="200" data-testid="m-subject" />
      </mat-form-field>
      <mat-form-field appearance="outline" class="full">
        <mat-label>Mensagem</mat-label>
        <textarea matInput rows="6" [(ngModel)]="draft.body" (ngModelChange)="changed()" maxlength="4000" data-testid="m-body"></textarea>
        <mat-hint>**negrito**, linhas começando com "- " viram lista, links ficam clicáveis. Variáveis: {{ builtinHint() }}.</mat-hint>
      </mat-form-field>

      @for (name of variableNames(); track name) {
        <mat-form-field appearance="outline">
          <mat-label>{{ varLabel(name) }}</mat-label>
          <input matInput [(ngModel)]="draft.variables[name]" (ngModelChange)="changed()" maxlength="500" [attr.data-testid]="'m-var-' + name" />
        </mat-form-field>
      }

      <h3>Destinatários ({{ selected().length }})</h3>
      @if (!reachesEveryone()) {
        <p class="hint">Você alcança pessoas do seu setor.</p>
      }
      <div class="chips">
        @for (r of selected(); track r.user_id) {
          <span class="chip" data-testid="m-selected">{{ r.name }}
            <button mat-icon-button (click)="remove(r)" aria-label="Remover"><mat-icon>close</mat-icon></button>
          </span>
        }
      </div>
      <mat-form-field appearance="outline" class="full">
        <mat-label>Buscar pessoa por nome ou e-mail</mat-label>
        <input matInput [(ngModel)]="query" (keyup.enter)="search()" data-testid="m-search" />
        <button matSuffix mat-icon-button (click)="search()" aria-label="Buscar"><mat-icon>search</mat-icon></button>
      </mat-form-field>
      <ul class="results">
        @for (r of results(); track r.user_id) {
          <li>
            <button mat-button (click)="add(r)" [disabled]="isSelected(r)" data-testid="m-result">{{ r.name }} · {{ r.email }}</button>
            @if (!r.channels.includes(draft.channel)) { <span class="warn">sem {{ channelName(draft.channel) }}</span> }
          </li>
        }
      </ul>

      @if (error()) {
        <p class="error" role="alert">{{ error() }}</p>
      }

      <div class="actions">
        <button mat-stroked-button (click)="runPreview()" [disabled]="busy()" data-testid="m-preview">Pré-visualizar</button>
        <button mat-stroked-button (click)="sendTest()" [disabled]="busy()" data-testid="m-test">Enviar teste para mim</button>
        <button mat-flat-button color="primary" (click)="send()" [disabled]="busy() || !canSend()" data-testid="m-send">
          Enviar para {{ preview()?.queued ?? 0 }} pessoa(s)
        </button>
      </div>
    </section>

    @if (preview(); as p) {
      <section class="preview" data-testid="m-preview-result">
        <h3>Prévia — {{ channelName(p.channel) }}</h3>
        <p>{{ p.queued }} vão receber · {{ p.skipped }} ficam de fora</p>
        <ul>
          @for (r of p.recipients; track r.user_id) {
            <li [class.out]="r.outcome !== 'queued'">{{ r.name || r.user_id }}: {{ outcomeLabel(r.outcome) }}</li>
          }
        </ul>
        @if (sample(); as s) {
          <h4>Como chega para {{ s.name }}</h4>
          @if (s.rendered?.html) {
            <div class="html" [innerHTML]="s.rendered?.html" data-testid="m-sample-html"></div>
          } @else {
            <pre data-testid="m-sample-text">{{ s.rendered?.title ? s.rendered?.title + '\n\n' : '' }}{{ s.rendered?.text }}</pre>
          }
          @if (s.rendered?.note) { <p class="hint">{{ s.rendered?.note }}</p> }
        }
      </section>
    }
  `,
  styles: [`
    .form { margin-top: 16px; }
    .row { display: flex; flex-wrap: wrap; gap: 12px; }
    .row mat-form-field { flex: 1 1 180px; }
    .full { width: 100%; }
    .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
    .chip { display: inline-flex; align-items: center; background: #e2e8f0; border-radius: 16px; padding-left: 10px; font-size: 13px; }
    .results { list-style: none; padding: 0; margin: 0 0 12px; }
    .warn { color: #b45309; font-size: 12px; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .preview { border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px; margin-top: 16px; background: #fff; }
    .preview li.out { color: #94a3b8; }
    .preview pre { white-space: pre-wrap; background: #f8fafc; padding: 12px; border-radius: 6px; }
    .html { border: 1px dashed #cbd5e1; border-radius: 6px; padding: 8px; }
    .hint { color: #64748b; font-size: 13px; }
    .error { color: #dc2626; }
  `]
})
export class MessageComposeComponent implements OnInit {
  private api = inject(MessagesService);
  private snack = inject(MatSnackBar);

  readonly channels = Object.entries(CHANNEL_NAMES).map(([key, label]) => ({ key, label }));
  draft: MessageDraft = this.emptyDraft();
  query = '';
  templates = signal<MessageTemplate[]>([]);
  builtin = signal<string[]>([]);
  results = signal<RecipientOption[]>([]);
  selected = signal<RecipientOption[]>([]);
  reachesEveryone = signal(false);
  preview = signal<PreviewResponse | null>(null);
  error = signal('');
  busy = signal(false);
  private idempotencyKey = newKey();

  ngOnInit(): void {
    this.api.listTemplates().subscribe({
      next: (res) => {
        this.templates.set(res.items);
        this.builtin.set(res.builtin_variables);
      }
    });
    this.search();
  }

  private emptyDraft(): MessageDraft {
    return { channel: 'in_app', subject: '', body: '', variables: {}, priority: 'normal', template_id: null, recipient_ids: [] };
  }

  channelName(channel: string): string {
    return CHANNEL_NAMES[channel] ?? channel;
  }

  outcomeLabel(outcome: string): string {
    return OUTCOME_LABELS[outcome] ?? outcome;
  }

  builtinHint(): string {
    return this.builtin().map((v) => this.varLabel(v)).join(', ');
  }

  varLabel(name: string): string {
    return `{{${name}}}`;
  }

  templatesFor(): MessageTemplate[] {
    return this.templates().filter((t) => !t.channels.length || t.channels.includes(this.draft.channel));
  }

  variableNames(): string[] {
    return customVariables([this.draft.subject, this.draft.body], this.builtin());
  }

  sample() {
    return this.preview()?.recipients.find((r) => r.outcome === 'queued') ?? null;
  }

  canSend(): boolean {
    return (this.preview()?.queued ?? 0) > 0;
  }

  /** Qualquer mudança invalida a prévia: só se envia o que foi visto. */
  changed(): void {
    this.preview.set(null);
  }

  applyTemplate(): void {
    const template = this.templates().find((t) => t.id === this.draft.template_id);
    if (template) {
      this.draft.subject = template.subject;
      this.draft.body = template.body;
    }
    this.changed();
  }

  search(): void {
    this.api.searchRecipients(this.query).subscribe({
      next: (res) => {
        this.results.set(res.items);
        this.reachesEveryone.set(res.reaches_everyone);
      },
      error: (err) => this.error.set(apiErrorMessage(err, 'Não foi possível buscar pessoas.'))
    });
  }

  isSelected(r: RecipientOption): boolean {
    return this.selected().some((s) => s.user_id === r.user_id);
  }

  add(r: RecipientOption): void {
    if (!this.isSelected(r)) this.selected.update((list) => [...list, r]);
    this.changed();
  }

  remove(r: RecipientOption): void {
    this.selected.update((list) => list.filter((s) => s.user_id !== r.user_id));
    this.changed();
  }

  private payload(): MessageDraft {
    const names = this.variableNames();
    const variables = Object.fromEntries(names.map((n) => [n, this.draft.variables[n] ?? '']));
    return { ...this.draft, variables, recipient_ids: this.selected().map((r) => r.user_id) };
  }

  runPreview(): void {
    if (!this.selected().length) {
      this.error.set('Escolha ao menos um destinatário.');
      return;
    }
    this.call(this.api.preview(this.payload()), (res) => this.preview.set(res), 'Não foi possível gerar a prévia.');
  }

  sendTest(): void {
    this.call(this.api.sendTest(this.payload()), () => {
      this.snack.open('Teste enfileirado para você.', 'OK', { duration: 3000 });
    }, 'Não foi possível enviar o teste.');
  }

  send(): void {
    this.call(this.api.send(this.payload(), this.idempotencyKey), (res) => {
      this.snack.open(`Envio enfileirado para ${res.queued_count} pessoa(s). Acompanhe no Histórico.`, 'OK', { duration: 4000 });
      this.draft = this.emptyDraft();
      this.selected.set([]);
      this.preview.set(null);
      this.idempotencyKey = newKey();
    }, 'Não foi possível enviar.');
  }

  private call<T>(request: Observable<T>, done: (value: T) => void, fallback: string): void {
    this.error.set('');
    this.busy.set(true);
    request.subscribe({
      next: (value) => {
        this.busy.set(false);
        done(value);
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(apiErrorMessage(err, fallback));
      }
    });
  }
}
