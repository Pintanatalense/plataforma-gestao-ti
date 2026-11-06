import { Component, OnInit, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { apiErrorMessage } from '../../../core/http/api-error';
import { MessageTemplate, MessagesService, TemplateInput } from '../../../core/services/messages.service';
import { CHANNEL_NAMES } from '../admin/channels.component';

@Component({
  selector: 'app-message-templates',
  standalone: true,
  imports: [FormsModule, MatButtonModule, MatCheckboxModule, MatFormFieldModule, MatInputModule, MatSelectModule, MatSnackBarModule],
  template: `
    <div class="toolbar">
      <button mat-flat-button color="primary" (click)="startNew()" data-testid="t-new">Novo modelo</button>
    </div>
    @if (error()) {
      <p class="error" role="alert">{{ error() }}</p>
    }

    @if (editing(); as e) {
      <section class="form" data-testid="t-form">
        <div class="row">
          <mat-form-field appearance="outline">
            <mat-label>Nome</mat-label>
            <input matInput [(ngModel)]="form.name" maxlength="150" data-testid="t-name" />
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Código</mat-label>
            <input matInput [(ngModel)]="form.code" maxlength="60" data-testid="t-code" />
            <mat-hint>minúsculas, números, ponto, hífen</mat-hint>
          </mat-form-field>
          <mat-form-field appearance="outline">
            <mat-label>Canais (vazio = todos)</mat-label>
            <mat-select multiple [(ngModel)]="form.channels">
              @for (c of channels; track c.key) {
                <mat-option [value]="c.key">{{ c.label }}</mat-option>
              }
            </mat-select>
          </mat-form-field>
        </div>
        <mat-form-field appearance="outline" class="full">
          <mat-label>Assunto</mat-label>
          <input matInput [(ngModel)]="form.subject" maxlength="200" />
        </mat-form-field>
        <mat-form-field appearance="outline" class="full">
          <mat-label>Mensagem</mat-label>
          <textarea matInput rows="6" [(ngModel)]="form.body" maxlength="4000" data-testid="t-body"></textarea>
        </mat-form-field>
        <mat-checkbox [(ngModel)]="form.is_active">Ativo (aparece para quem envia)</mat-checkbox>
        <div class="actions">
          <button mat-flat-button color="primary" (click)="save(e)" data-testid="t-save">Salvar</button>
          <button mat-button (click)="editing.set(null)">Cancelar</button>
        </div>
      </section>
    }

    <ul class="list">
      @for (t of items(); track t.id) {
        <li data-testid="t-item">
          <strong>{{ t.name }}</strong> <code>{{ t.code }}</code>
          {{ t.is_active ? '' : '(desativado)' }}
          <span class="muted">{{ t.channels.length ? channelNames(t.channels) : 'todos os canais' }}</span>
          <button mat-button (click)="edit(t)">Editar</button>
          <button mat-button color="warn" (click)="remove(t)" data-testid="t-delete">Excluir</button>
        </li>
      } @empty {
        <li class="muted">Nenhum modelo cadastrado.</li>
      }
    </ul>
  `,
  styles: [`
    .toolbar { margin: 16px 0 8px; }
    .form { border: 1px solid #e2e8f0; border-radius: 8px; padding: 12px 16px; margin-bottom: 16px; background: #fff; }
    .row { display: flex; flex-wrap: wrap; gap: 12px; }
    .row mat-form-field { flex: 1 1 180px; }
    .full { width: 100%; }
    .actions { display: flex; gap: 8px; margin-top: 8px; }
    .list { list-style: none; padding: 0; }
    .list li { padding: 8px 0; border-bottom: 1px solid #f1f5f9; }
    .muted { color: #64748b; font-size: 13px; margin: 0 8px; }
    .error { color: #dc2626; }
  `]
})
export class MessageTemplatesComponent implements OnInit {
  private api = inject(MessagesService);
  private snack = inject(MatSnackBar);

  readonly channels = Object.entries(CHANNEL_NAMES).map(([key, label]) => ({ key, label }));
  items = signal<MessageTemplate[]>([]);
  error = signal('');
  /** 'new' ou o id do modelo em edição; null = formulário fechado. */
  editing = signal<string | null>(null);
  form: TemplateInput = this.blank();

  ngOnInit(): void {
    this.load();
  }

  private blank(): TemplateInput {
    return { code: '', name: '', channels: [], subject: '', body: '', is_active: true };
  }

  channelNames(channels: string[]): string {
    return channels.map((c) => CHANNEL_NAMES[c] ?? c).join(', ');
  }

  load(): void {
    this.api.listTemplates().subscribe({
      next: (res) => this.items.set(res.items),
      error: (err) => this.error.set(apiErrorMessage(err, 'Não foi possível carregar os modelos.'))
    });
  }

  startNew(): void {
    this.form = this.blank();
    this.editing.set('new');
  }

  edit(t: MessageTemplate): void {
    this.form = { code: t.code, name: t.name, channels: [...t.channels], subject: t.subject, body: t.body, is_active: t.is_active };
    this.editing.set(t.id);
  }

  save(id: string): void {
    this.error.set('');
    const request = id === 'new' ? this.api.createTemplate(this.form) : this.api.updateTemplate(id, this.form);
    request.subscribe({
      next: () => {
        this.editing.set(null);
        this.snack.open('Modelo salvo.', 'OK', { duration: 3000 });
        this.load();
      },
      error: (err) => this.error.set(apiErrorMessage(err, 'Não foi possível salvar o modelo.'))
    });
  }

  remove(t: MessageTemplate): void {
    if (!confirm(`Excluir o modelo "${t.name}"? Envios antigos guardam o texto que foi usado.`)) return;
    this.api.deleteTemplate(t.id).subscribe({
      next: () => this.load(),
      error: (err) => this.error.set(apiErrorMessage(err, 'Não foi possível excluir o modelo.'))
    });
  }
}
