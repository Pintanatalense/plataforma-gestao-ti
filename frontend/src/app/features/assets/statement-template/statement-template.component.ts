import { ChangeDetectorRef, Component, ElementRef, OnInit, ViewChild, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';
import { apiErrorMessage } from '../../../core/http/api-error';
import { AssetService, StatementTemplate } from '../../../core/services/asset.service';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';

const FIELD_PATTERN = /\{\{\s*([a-z_]+)\s*\}\}/g;

@Component({
  selector: 'app-statement-template',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterModule, MatButtonModule, MatIconModule, MatSnackBarModule, LoadStateComponent],
  template: `
    <div class="page-container">
      <div class="page-header">
        <div class="title-area">
          <button mat-button routerLink="/assets"><mat-icon>arrow_back</mat-icon> Ativos</button>
          <h1>Modelo do Termo de Responsabilidade</h1>
          <p class="subtitle">Edite o texto para seguir o padrão da empresa. Os dados do colaborador e do equipamento continuam sendo preenchidos sozinhos.</p>
        </div>
      </div>

      <app-load-state [loading]="isLoading" [error]="loadError" loadingText="Carregando o modelo…" (retry)="load()"></app-load-state>

      <div class="editor" *ngIf="data">
        <section class="main">
          <div class="status" data-testid="template-status" [class.custom]="!data.is_default">
            <mat-icon>{{ data.is_default ? 'description' : 'edit_document' }}</mat-icon>
            {{ data.is_default ? 'Modelo padrão do sistema (nenhum modelo próprio salvo).' : 'Modelo próprio da empresa.' }}
          </div>

          <textarea #editor class="area" data-testid="template-text" rows="26" spellcheck="true" [(ngModel)]="text"
                    (ngModelChange)="onChange()" [disabled]="!canEdit" aria-label="Texto do termo"></textarea>

          <p class="warn" data-testid="template-unknown" *ngIf="unknown.length">
            <mat-icon>warning</mat-icon>
            Campos desconhecidos (vão aparecer como escritos): {{ unknown.join(', ') }}
          </p>

          <div class="actions" *ngIf="canEdit">
            <button mat-stroked-button type="button" data-testid="template-preview" [disabled]="busy || !text.trim()" (click)="preview()">
              <mat-icon>visibility</mat-icon> Ver prévia
            </button>
            <button mat-stroked-button type="button" color="warn" data-testid="template-reset" [disabled]="busy || data.is_default" (click)="restoreDefault()">
              <mat-icon>restore</mat-icon> Voltar ao modelo padrão
            </button>
            <button mat-flat-button color="primary" type="button" data-testid="template-save" [disabled]="busy || !dirty || !text.trim()" (click)="save()">
              {{ saving ? 'Salvando…' : 'Salvar modelo' }}
            </button>
          </div>
        </section>

        <aside class="help">
          <h3>Campos automáticos</h3>
          <p>Clique para inserir no ponto do cursor.</p>
          <div class="chips">
            <button type="button" class="chip" *ngFor="let f of fieldList" [title]="f.description" (click)="insert('{{' + f.name + '}}')" [disabled]="!canEdit">{{ '{{' + f.name + '}}' }}</button>
          </div>
          <h3>Blocos prontos</h3>
          <p>Coloque sozinhos em uma linha.</p>
          <div class="chips">
            <button type="button" class="chip" *ngFor="let b of blockList" [title]="b.description" (click)="insert('\\n{{' + b.name + '}}\\n')" [disabled]="!canEdit">{{ '{{' + b.name + '}}' }}</button>
          </div>
          <h3>Formatação</h3>
          <ul>
            <li><code># Título</code> título do documento</li>
            <li><code>&gt; Subtítulo</code> linha pequena abaixo do título</li>
            <li><code>## Seção</code> título de seção</li>
            <li><code>1. item</code> ou <code>- item</code> listas</li>
            <li><code>**negrito**</code> destaque</li>
            <li>Linha em branco separa parágrafos.</li>
          </ul>
          <p class="note">O modelo é só texto: não aceita HTML. O visual (tabelas, assinaturas) é padronizado pelo sistema.</p>
        </aside>
      </div>
    </div>
  `,
  styles: [
    `
      .editor { display: grid; grid-template-columns: minmax(0, 1fr) 320px; gap: 24px; align-items: start; }
      @media (max-width: 960px) { .editor { grid-template-columns: 1fr; } }
      .main, .help { background: #fff; border-radius: 12px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,.12); }
      .status { display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 8px; background: #f1f5f9; color: #334155; margin-bottom: 12px; }
      .status.custom { background: #eff6ff; color: #1e40af; }
      .area { width: 100%; box-sizing: border-box; font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px; line-height: 1.5; padding: 12px; border: 1px solid #cbd5e1; border-radius: 8px; resize: vertical; }
      .warn { display: flex; align-items: center; gap: 6px; color: #b45309; margin: 8px 0 0; }
      .actions { display: flex; gap: 12px; justify-content: flex-end; flex-wrap: wrap; margin-top: 16px; }
      .help h3 { margin: 12px 0 4px; font-size: 14px; }
      .help p { margin: 0 0 8px; color: #64748b; font-size: 12px; }
      .help .note { margin-top: 12px; }
      .help ul { padding-left: 18px; margin: 0; font-size: 12px; color: #475569; }
      .chips { display: flex; flex-wrap: wrap; gap: 6px; }
      .chip { border: 1px solid #cbd5e1; background: #f8fafc; border-radius: 999px; padding: 2px 10px; font-size: 12px; cursor: pointer; font-family: ui-monospace, Menlo, Consolas, monospace; }
      .chip:hover:not(:disabled) { background: #e2e8f0; }
    `
  ]
})
export class StatementTemplateComponent implements OnInit {
  private assets = inject(AssetService);
  private snackBar = inject(MatSnackBar);
  private cdr = inject(ChangeDetectorRef);

  @ViewChild('editor') editor?: ElementRef<HTMLTextAreaElement>;

  data: StatementTemplate | null = null;
  text = '';
  saved = '';
  unknown: string[] = [];
  isLoading = true;
  loadError: string | null = null;
  saving = false;
  busy = false;

  canEdit = true;

  get fieldList(): { name: string; description: string }[] {
    return Object.entries(this.data?.fields ?? {}).map(([name, description]) => ({ name, description }));
  }

  get blockList(): { name: string; description: string }[] {
    return Object.entries(this.data?.blocks ?? {}).map(([name, description]) => ({ name, description }));
  }

  get dirty(): boolean {
    return this.text !== this.saved;
  }

  ngOnInit(): void {
    this.load();
  }

  load(): void {
    this.isLoading = true;
    this.loadError = null;
    this.assets.getStatementTemplate().subscribe({
      next: (data) => {
        this.apply(data);
        this.isLoading = false;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.data = null;
        this.isLoading = false;
        this.loadError = apiErrorMessage(err, 'Não foi possível carregar o modelo do termo.');
        this.cdr.markForCheck();
      }
    });
  }

  private apply(data: StatementTemplate): void {
    this.data = data;
    this.text = data.template;
    this.saved = data.template;
    this.refreshUnknown();
  }

  onChange(): void {
    this.refreshUnknown();
  }

  /** Mesma regra do backend: {{campo}} que o sistema não conhece. */
  private refreshUnknown(): void {
    const known = new Set([...Object.keys(this.data?.fields ?? {}), ...Object.keys(this.data?.blocks ?? {})]);
    const found = new Set<string>();
    for (const match of this.text.matchAll(FIELD_PATTERN)) {
      if (!known.has(match[1])) found.add(match[1]);
    }
    this.unknown = [...found].sort();
  }

  insert(snippet: string): void {
    const el = this.editor?.nativeElement;
    const value = snippet.replace(/\\n/g, '\n');
    if (!el) {
      this.text += value;
    } else {
      const start = el.selectionStart ?? this.text.length;
      const end = el.selectionEnd ?? start;
      this.text = this.text.slice(0, start) + value + this.text.slice(end);
      setTimeout(() => {
        el.focus();
        el.selectionStart = el.selectionEnd = start + value.length;
      });
    }
    this.refreshUnknown();
    this.cdr.markForCheck();
  }

  preview(): void {
    this.busy = true;
    this.assets.previewStatementTemplate(this.text).subscribe({
      next: () => {
        this.busy = false;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.busy = false;
        this.snackBar.open(apiErrorMessage(err, 'Não foi possível gerar a prévia.'), 'Fechar', { duration: 5000 });
        this.cdr.markForCheck();
      }
    });
  }

  save(): void {
    this.saving = true;
    this.busy = true;
    this.assets.saveStatementTemplate(this.text).subscribe({
      next: (data) => {
        this.saving = false;
        this.busy = false;
        this.apply(data);
        this.snackBar.open('Modelo do termo salvo.', 'OK', { duration: 4000 });
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.saving = false;
        this.busy = false;
        this.snackBar.open(apiErrorMessage(err, 'Não foi possível salvar o modelo.'), 'Fechar', { duration: 6000 });
        this.cdr.markForCheck();
      }
    });
  }

  restoreDefault(): void {
    if (!confirm('Voltar ao modelo padrão do sistema? O modelo próprio da empresa será apagado.')) return;
    this.busy = true;
    this.assets.resetStatementTemplate().subscribe({
      next: (data) => {
        this.busy = false;
        this.apply(data);
        this.snackBar.open('Modelo padrão restaurado.', 'OK', { duration: 4000 });
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.busy = false;
        this.snackBar.open(apiErrorMessage(err, 'Não foi possível restaurar o modelo padrão.'), 'Fechar', { duration: 6000 });
        this.cdr.markForCheck();
      }
    });
  }
}
