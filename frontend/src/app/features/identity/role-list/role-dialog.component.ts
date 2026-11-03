import { Component, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { IdentityService, Role, Permission } from '../../../core/services/identity.service';

@Component({
  selector: 'app-role-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
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

        <mat-form-field appearance="outline">
          <mat-label>Permissões</mat-label>
          <mat-select formControlName="permission_ids" multiple>
            <mat-option *ngFor="let perm of permissions" [value]="perm.id"
              >{{ perm.code }} ({{ perm.description }})</mat-option
            >
          </mat-select>
        </mat-form-field>
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancelar</button>
      <button mat-flat-button color="primary" [disabled]="form.invalid" (click)="save()">
        Salvar
      </button>
    </mat-dialog-actions>
  `,
  styles: [
    `
      .dialog-form {
        display: flex;
        flex-direction: column;
        gap: 16px;
        margin-top: 8px;
        min-width: 400px;
      }
    `,
  ],
})
export class RoleDialogComponent implements OnInit {
  data = inject<Role | null>(MAT_DIALOG_DATA);

  private fb = inject(FormBuilder);
  private identityService = inject(IdentityService);
  dialogRef = inject(MatDialogRef<RoleDialogComponent>);

  permissions: Permission[] = [];

  form: any;

  constructor() {
    this.form = this.fb.group({
      name: [this.data?.name || '', Validators.required],
      description: [this.data?.description || ''],
      permission_ids: [this.data?.permissions?.map((p: any) => p.id) || []],
    });
  }

  ngOnInit(): void {
    // Críticas não entram em perfil (o backend recusa): ficam fora da lista.
    this.identityService
      .getPermissions()
      .subscribe((perms: Permission[]) => (this.permissions = perms.filter((p) => !p.is_critical)));
  }

  save() {
    if (this.form.valid) {
      this.dialogRef.close(this.form.value);
    }
  }
}
