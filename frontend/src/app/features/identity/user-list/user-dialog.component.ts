import { Component, Inject, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { IdentityService, Role, User } from '../../../core/services/identity.service';
import { OrganizationService, Employee } from '../../../core/services/organization.service';

@Component({
  selector: 'app-user-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatSlideToggleModule
  ],
  template: `
    <h2 mat-dialog-title>{{ data ? 'Editar' : 'Novo' }} Usuário</h2>
    <mat-dialog-content>
      <form [formGroup]="form" class="dialog-form">
        
        <mat-form-field appearance="outline">
          <mat-label>Colaborador</mat-label>
          <mat-select formControlName="employee_id" required>
            <mat-option *ngFor="let emp of employees" [value]="emp.id">{{ emp.name }} ({{ emp.registration }})</mat-option>
          </mat-select>
        </mat-form-field>

        <mat-form-field appearance="outline">
          <mat-label>Email</mat-label>
          <input matInput formControlName="email" type="email" required>
        </mat-form-field>
        
        <mat-form-field appearance="outline" *ngIf="!data">
          <mat-label>Senha Temporária</mat-label>
          <input matInput formControlName="password" required>
        </mat-form-field>

        <mat-form-field appearance="outline">
          <mat-label>Perfis</mat-label>
          <mat-select formControlName="role_ids" multiple>
            <mat-option *ngFor="let role of roles" [value]="role.id">{{ role.name }}</mat-option>
          </mat-select>
        </mat-form-field>

        <mat-slide-toggle formControlName="is_admin">
          Administrador Global
        </mat-slide-toggle>

      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancelar</button>
      <button mat-flat-button color="primary" [disabled]="form.invalid" (click)="save()">Salvar</button>
    </mat-dialog-actions>
  `,
  styles: [`
    .dialog-form {
      display: flex;
      flex-direction: column;
      gap: 16px;
      margin-top: 8px;
      min-width: 400px;
    }
  `]
})
export class UserDialogComponent implements OnInit {
  private fb = inject(FormBuilder);
  private identityService = inject(IdentityService);
  private orgService = inject(OrganizationService);
  dialogRef = inject(MatDialogRef<UserDialogComponent>);

  roles: Role[] = [];
  employees: Employee[] = [];

  form: any;

  constructor(@Inject(MAT_DIALOG_DATA) public data: User | null) {
    this.form = this.fb.group({
      employee_id: [this.data?.employee_id || '', Validators.required],
      email: [this.data?.email || '', [Validators.required, Validators.email]],
      password: [this.data ? '' : 'temporaria-123', this.data ? [] : Validators.required],
      role_ids: [this.data?.roles?.map((r: any) => r.id) || []],
      is_admin: [this.data?.is_admin || false]
    });
  }

  ngOnInit(): void {
    this.identityService.getRoles().subscribe((roles: any) => this.roles = roles);
    this.orgService.getEmployees().subscribe((emps: any) => this.employees = emps.filter((e: any) => e.is_active));
  }

  save() {
    if (this.form.valid) {
      this.dialogRef.close(this.form.value);
    }
  }
}
