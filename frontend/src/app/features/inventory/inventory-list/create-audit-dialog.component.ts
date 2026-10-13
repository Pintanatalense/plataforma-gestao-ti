import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';

import { OrganizationService, Unit, Employee } from '../../../core/services/organization.service';

@Component({
  selector: 'app-create-audit-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatIconModule
  ],
  template: `
    <h2 mat-dialog-title>Nova Auditoria de Inventário</h2>
    <mat-dialog-content>
      <form [formGroup]="form" class="dialog-form">
        <mat-form-field appearance="outline">
          <mat-label>Título / Identificação</mat-label>
          <input matInput formControlName="name" placeholder="Ex: Inventário Anual 2026 - Matriz" required>
          <mat-icon matPrefix>title</mat-icon>
        </mat-form-field>

        <mat-form-field appearance="outline">
          <mat-label>Unidade Física</mat-label>
          <mat-select formControlName="unit_id" required>
            <mat-option *ngFor="let u of units" [value]="u.id">{{ u.name }}</mat-option>
          </mat-select>
          <mat-icon matPrefix>business</mat-icon>
        </mat-form-field>

        <mat-form-field appearance="outline">
          <mat-label>Auditor Responsável</mat-label>
          <mat-select formControlName="auditor_id" required>
            <mat-option *ngFor="let emp of employees" [value]="emp.id">{{ emp.name }} ({{ emp.registration }})</mat-option>
          </mat-select>
          <mat-icon matPrefix>person</mat-icon>
        </mat-form-field>
      </form>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>Cancelar</button>
      <button mat-flat-button color="primary" [disabled]="form.invalid" (click)="save()">Iniciar Auditoria</button>
    </mat-dialog-actions>
  `,
  styles: [`
    .dialog-form {
      display: flex;
      flex-direction: column;
      gap: 16px;
      margin-top: 12px;
      min-width: 360px;
    }
  `]
})
export class CreateAuditDialogComponent implements OnInit {
  private fb = inject(FormBuilder);
  private orgService = inject(OrganizationService);
  dialogRef = inject(MatDialogRef<CreateAuditDialogComponent>);

  form = this.fb.group({
    name: ['', Validators.required],
    unit_id: ['', Validators.required],
    auditor_id: ['', Validators.required]
  });

  units: Unit[] = [];
  employees: Employee[] = [];

  ngOnInit(): void {
    this.orgService.getUnits().subscribe({
      next: (units) => {
        this.units = units;
        if (units.length > 0) this.form.get('unit_id')?.setValue(units[0].id);
      }
    });

    this.orgService.getEmployees().subscribe({
      next: (emps) => {
        this.employees = emps;
        if (emps.length > 0) this.form.get('auditor_id')?.setValue(emps[0].id);
      }
    });
  }

  save(): void {
    if (this.form.valid) {
      this.dialogRef.close(this.form.value);
    }
  }
}
