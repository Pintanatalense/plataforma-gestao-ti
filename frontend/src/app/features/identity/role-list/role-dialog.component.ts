import { Component, inject, OnInit, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatButtonModule } from '@angular/material/button';
import { apiErrorMessage } from '../../../core/http/api-error';
import { IdentityService, Role, Permission, groupByModule } from '../../../core/services/identity.service';

@Component({
  selector: 'app-role-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatCheckboxModule,
    MatButtonModule,
  ],
  template: `
    <h2 mat-dialog-title>{{ data ? 'Editar' : 'Novo' }} Perfil</h2>
    <mat-dialog-content>
      <form [formGroup]="form" class="dialog-form">
        <mat-form-field appearance="outline">
          <mat-label>Nome</mat-label>
          <input matInput formControlName="name" required />
        </mat-form-field>

        <mat-form-field appearance="outline">
          <mat-label>Descrição</mat-label>
          <input matInput formControlName="description" />
        </mat-form-field>

        <p class="hint">
          Permissões críticas (backups, importação, zerar a base e concessão de críticas) não entram em perfil:
          são concedidas a cada pessoa, na tela de usuários.
        </p>

        @if (loadError()) {
          <p class="error" role="alert" data-testid="permissions-error">{{ loadError() }}</p>
        }

        @for (group of groups(); track group.module) {
          <fieldset class="module" [attr.data-testid]="'module-' + group.module">
            <legend>{{ group.label }}</legend>
            @for (perm of group.items; track perm.id) {
              <div class="perm">
                <mat-checkbox [checked]="selected.has(perm.id)" (change)="toggle(perm.id, $event.checked)"
                              [attr.data-testid]="'perm-' + perm.code">
                  {{ perm.label || perm.code }}
                </mat-checkbox>
                <span class="risk" [class]="'risk risk-' + perm.risk">{{ perm.risk_label || perm.risk }}</span>
                <div class="desc">{{ perm.description }} <code>{{ perm.code }}</code></div>
              </div>
            }
          </fieldset>
        }
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancelar</button>
      <button mat-flat-button color="primary" [disabled]="form.invalid || !!loadError()" (click)="save()">
        Salvar
      </button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .dialog-form {
        display: flex;
        flex-direction: column;
        gap: 12px;
        margin-top: 8px;
        min-width: 420px;
        max-width: 640px;
      }
      .hint {
        font-size: 13px;
        color: #64748b;
        margin: 0;
      }
      .error {
        color: #b91c1c;
        margin: 0;
      }
      .module {
        border: 1px solid #e2e8f0;
        border-radius: 8px;
        padding: 8px 12px;
      }
      .module legend {
        font-weight: 600;
        padding: 0 4px;
      }
      .perm {
        padding: 2px 0;
      }
      .desc {
        font-size: 12px;
        color: #64748b;
        margin-left: 40px;
      }
      .desc code {
        font-size: 11px;
        color: #94a3b8;
      }
      .risk {
        font-size: 11px;
        border-radius: 10px;
        padding: 1px 8px;
        margin-left: 6px;
        background: #f1f5f9;
        color: #475569;
      }
      .risk-alteracao {
        background: #fef9c3;
        color: #854d0e;
      }
      .risk-aprovacao,
      .risk-execucao,
      .risk-administracao {
        background: #fee2e2;
        color: #991b1b;
      }
    `,
  ],
})
export class RoleDialogComponent implements OnInit {
  data = inject<Role | null>(MAT_DIALOG_DATA);

  private fb = inject(FormBuilder);
  private identityService = inject(IdentityService);
  dialogRef = inject(MatDialogRef<RoleDialogComponent>);

  groups = signal<{ module: string; label: string; items: Permission[] }[]>([]);
  selected = new Set<string>(this.data?.permissions?.map((p) => p.id) ?? []);
  loadError = signal<string | null>(null);

  form = this.fb.group({
    name: [this.data?.name || '', Validators.required],
    description: [this.data?.description || ''],
  });

  ngOnInit(): void {
    // Críticas não entram em perfil (o backend recusa): ficam fora da lista.
    this.identityService.getPermissions().subscribe({
      next: (perms: Permission[]) => this.groups.set(groupByModule(perms.filter((p) => !p.is_critical))),
      // sem a lista, salvar apagaria as permissões do perfil: bloqueia
      error: (err) => this.loadError.set(apiErrorMessage(err, 'Não foi possível carregar as permissões.')),
    });
  }

  toggle(id: string, checked: boolean) {
    if (checked) this.selected.add(id);
    else this.selected.delete(id);
  }

  save() {
    if (this.form.valid && !this.loadError()) {
      this.dialogRef.close({ ...this.form.value, permission_ids: [...this.selected] });
    }
  }
}
