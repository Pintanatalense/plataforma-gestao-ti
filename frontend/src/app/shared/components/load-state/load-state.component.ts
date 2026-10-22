import { ChangeDetectionStrategy, Component, input, output } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';

/**
 * Estados de uma área que depende de dados da API: carregando, falha (com "Tentar novamente"), vazio e conteúdo.
 *
 * Regra: uma falha de comunicação NUNCA aparece como "lista vazia". Quem usa passa `error` (texto) quando a chamada
 * falhou e `empty` só quando a chamada deu certo e não trouxe itens.
 *
 *   <app-load-state [loading]="loading" [error]="error" [empty]="items.length === 0"
 *                   emptyText="Nenhum chamado encontrado." (retry)="load()">
 *     ...conteúdo...
 *   </app-load-state>
 *
 * Precedência: carregando > erro > vazio > conteúdo.
 */
@Component({
  selector: 'app-load-state',
  standalone: true,
  imports: [MatButtonModule, MatIconModule, MatProgressSpinnerModule],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    @if (loading()) {
      <div class="state state-loading" role="status" aria-live="polite" data-testid="state-loading">
        <mat-spinner diameter="32"></mat-spinner>
        <span>{{ loadingText() }}</span>
      </div>
    } @else if (error()) {
      <div class="state state-error" role="alert" data-testid="state-error">
        <mat-icon aria-hidden="true">error_outline</mat-icon>
        <span class="message">{{ error() }}</span>
        <button mat-stroked-button type="button" data-testid="state-retry" (click)="retry.emit()">
          <mat-icon>refresh</mat-icon> {{ retryLabel() }}
        </button>
      </div>
    } @else if (empty()) {
      <div class="state state-empty" data-testid="state-empty">
        <mat-icon aria-hidden="true">{{ emptyIcon() }}</mat-icon>
        <span class="message">{{ emptyText() }}</span>
        <ng-content select="[empty-action]"></ng-content>
      </div>
    } @else {
      <ng-content></ng-content>
    }
  `,
  styles: [
    `
      :host { display: block; }
      .state {
        display: flex; flex-direction: column; align-items: center; justify-content: center;
        gap: 12px; padding: 32px 16px; text-align: center; color: var(--mat-sys-on-surface-variant, #475569);
      }
      .state mat-icon { font-size: 40px; width: 40px; height: 40px; opacity: 0.8; }
      .state-error { color: var(--mat-sys-error, #b3261e); }
      .state-error .message { color: inherit; max-width: 560px; }
      .state-empty .message { max-width: 560px; }
    `
  ]
})
export class LoadStateComponent {
  readonly loading = input(false);
  /** Texto do erro; vazio/nulo = sem erro. */
  readonly error = input<string | null>(null);
  readonly empty = input(false);
  readonly emptyText = input('Nada para mostrar.');
  readonly emptyIcon = input('inbox');
  readonly loadingText = input('Carregando…');
  readonly retryLabel = input('Tentar novamente');
  readonly retry = output<void>();
}
