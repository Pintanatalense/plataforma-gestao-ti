import { Component, Inject, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { OrganizationService, Employee, Sector } from '../../../core/services/organization.service';

@Component({
  selector: 'app-employee-dialog',
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
    <h2 mat-dialog-title>{{ data ? 'Editar' : 'Novo' }} Colaborador</h2>
    <mat-dialog-content>
      <form [formGroup]="form" class="dialog-form">
        <mat-form-field appearance="outline">
          <mat-label>Setor</mat-label>
          <mat-select formControlName="sector_id" required>
            <mat-option *ngFor="let sector of sectors" [value]="sector.id">{{ sector.unit?.name }} - {{ sector.name }}</mat-option>
          </mat-select>
        </mat-form-field>

        <mat-form-field appearance="outline">
          <mat-label>Matrícula</mat-label>
          <input matInput formControlName="registration" required>
        </mat-form-field>
        
        <mat-form-field appearance="outline">
          <mat-label>Nome Completo</mat-label>
          <input matInput formControlName="name" required>
        </mat-form-field>

        <mat-form-field appearance="outline">
          <mat-label>Cargo</mat-label>
          <input matInput formControlName="job_title" required>
        </mat-form-field>

        <mat-slide-toggle formControlName="is_active" *ngIf="data">
          Ativo
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
      min-width: 300px;
    }
  `]
})
export class EmployeeDialogComponent implements OnInit {
  private fb = inject(FormBuilder);
  private orgService = inject(OrganizationService);
  dialogRef = inject(MatDialogRef<EmployeeDialogComponent>);

  sectors: Sector[] = [];

  form: any;

  constructor(@Inject(MAT_DIALOG_DATA) public data: Employee | null) {
    this.form = this.fb.group({
      sector_id: [this.data?.sector_id || '', Validators.required],
      registration: [this.data?.registration || '', Validators.required],
      name: [this.data?.name || '', Validators.required],
      job_title: [this.data?.job_title || '', Validators.required],
      is_active: [this.data ? this.data.is_active : true]
    });
  }

  ngOnInit(): void {
    this.orgService.getSectors().subscribe((sectors: any) => {
      this.sectors = sectors.filter((s: any) => s.is_active);
    });
  }

  save() {
    if (this.form.valid) {
      this.dialogRef.close(this.form.value);
    }
  }
}
