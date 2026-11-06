import { Component, computed, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { AuthService } from '../../../core/auth/auth.service';
import { apiErrorMessage } from '../../../core/http/api-error';
import {
  CriticalGrant,
  EffectivePermission,
  IdentityService,
  Permission,
  User,
  groupByModule,
} from '../../../core/services/identity.service';

const VIA_LABELS: Record<string, string> = {
  setup: 'assistente de instalação',
  migration: 'atualização do sistema',
  cli: 'comando no servidor',
  api: 'tela de usuários',
};

/** Acesso efetivo da conta (o que ela pode e por quê) e concessão individual das permissões críticas. */
@Component({
  selector: 'app-user-access-dialog',
  standalone: true,
  imports: [CommonModule, FormsModule, MatDialogModule, MatButtonModule, MatFormFieldModule, MatInputModule, MatSelectModule],
  template: `
    <h2 mat-dialog-title>Acesso de {{ user.email }}</h2>
    <mat-dialog-content class="content">
      @if (error()) {
        <p class="error" role="alert" data-testid="access-error">{{ error() }}</p>
      }

      <section>
        <h3>Permissões críticas</h3>
        <p class="hint">Valem só por concessão individual, nem perfil nem "Administrador" as dão.</p>
        @for (g of grants(); track g.permission) {
          <div class="grant" [attr.data-testid]="'grant-' + g.permission">
            <strong>{{ g.label }}</strong>
            <span class="meta">— {{ via(g.granted_via) }}, {{ g.granted_at | date: 'dd/MM/yyyy HH:mm' }}{{ g.reason ? ': ' + g.reason : '' }}</span>
            @if (canGrant) {
              <button mat-button color="warn" (click)="revoke(g)" [disabled]="busy()">Revogar</button>
            }
          </div>
        } @empty {
          <p class="muted" data-testid="no-grants">Nenhuma permissão crítica.</p>
        }

        @if (canGrant && grantable().length > 0) {
          <div class="grant-form">
            <mat-form-field appearance="outline">
              <mat-label>Conceder</mat-label>
              <mat-select [(ngModel)]="newPermission" data-testid="grant-select">
                @for (p of grantable(); track p.code) {
                  <mat-option [value]="p.code">{{ p.label || p.code }}</mat-option>
                }
              </mat-select>
            </mat-form-field>
            <mat-form-field appearance="outline">
              <mat-label>Motivo (vai para a auditoria)</mat-label>
              <input matInput [(ngModel)]="reason" maxlength="255" data-testid="grant-reason" />
            </mat-form-field>
            <button mat-flat-button color="primary" data-testid="grant-submit"
                    [disabled]="busy() || !newPermission || reason.trim().length < 5" (click)="grant()">
              Conceder
            </button>
          </div>
        }
      </section>

      <section>
        <h3>Acesso efetivo</h3>
        @for (group of groups(); track group.module) {
          <div class="module" [attr.data-testid]="'effective-' + group.module">
            <h4>{{ group.label }}</h4>
            @for (p of group.items; track p.code) {
              <div class="perm">
                {{ p.label }} <span class="risk">{{ p.risk_label }}</span>
                <span class="meta">— {{ p.sources.join(', ') }}</span>
              </div>
            }
          </div>
        } @empty {
          @if (!loading()) {
            <p class="muted">Esta conta não tem nenhuma permissão.</p>
          }
        }
      </section>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Fechar</button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .content { min-width: 440px; max-width: 680px; }
      h3 { margin: 12px 0 4px; font-size: 16px; }
      h4 { margin: 8px 0 2px; font-size: 14px; color: #334155; }
      .hint, .muted, .meta { font-size: 12px; color: #64748b; }
      .error { color: #b91c1c; }
      .perm, .grant { font-size: 13px; padding: 2px 0; }
      .risk { font-size: 11px; border-radius: 10px; padding: 1px 8px; background: #f1f5f9; color: #475569; }
      .grant-form { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
    `,
  ],
})
export class UserAccessDialogComponent implements OnInit {
  user = inject<User>(MAT_DIALOG_DATA);
  private identity = inject(IdentityService);
  private auth = inject(AuthService);

  /** Só quem tem a permissão de conceder críticas vê os botões (o backend confere de novo). */
  readonly canGrant = this.auth.hasPermission('identity.critical.grant');

  groups = signal<{ module: string; label: string; items: EffectivePermission[] }[]>([]);
  grants = signal<CriticalGrant[]>([]);
  criticalCatalog = signal<Permission[]>([]);
  loading = signal(true);
  busy = signal(false);
  error = signal<string | null>(null);
  newPermission = '';
  reason = '';

  /** Críticas que a conta ainda não tem. */
  grantable = computed(() => {
    const has = new Set(this.grants().map((g) => g.permission));
    return this.criticalCatalog().filter((p) => !has.has(p.code));
  });

  ngOnInit(): void {
    this.reload();
    if (this.canGrant) {
      this.identity.getPermissions().subscribe({
        next: (perms) => this.criticalCatalog.set(perms.filter((p) => p.is_critical)),
        error: () => this.criticalCatalog.set([]),
      });
    }
  }

  via(code: string): string {
    return VIA_LABELS[code] ?? code;
  }

  reload(): void {
    this.loading.set(true);
    this.identity.getEffectiveAccess(this.user.id).subscribe({
      next: (items) => {
        this.groups.set(groupByModule(items));
        this.loading.set(false);
      },
      error: (err) => {
        this.error.set(apiErrorMessage(err, 'Não foi possível carregar o acesso desta conta.'));
        this.loading.set(false);
      },
    });
    this.identity.getCriticalGrants(this.user.id).subscribe({
      next: (grants) => this.grants.set(grants),
      error: (err) => this.error.set(apiErrorMessage(err, 'Não foi possível carregar as permissões críticas.')),
    });
  }

  grant(): void {
    this.busy.set(true);
    this.error.set(null);
    this.identity.grantCritical(this.user.id, this.newPermission, this.reason.trim()).subscribe({
      next: () => {
        this.busy.set(false);
        this.newPermission = '';
        this.reason = '';
        this.reload();
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(apiErrorMessage(err, 'Não foi possível conceder a permissão.'));
      },
    });
  }

  revoke(g: CriticalGrant): void {
    const reason = window.prompt(`Motivo para revogar "${g.label}" (vai para a auditoria):`);
    if (!reason || reason.trim().length < 5) return;
    this.busy.set(true);
    this.error.set(null);
    this.identity.revokeCritical(this.user.id, g.permission, reason.trim()).subscribe({
      next: () => {
        this.busy.set(false);
        this.reload();
      },
      error: (err) => {
        this.busy.set(false);
        this.error.set(apiErrorMessage(err, 'Não foi possível revogar a permissão.'));
      },
    });
  }
}
