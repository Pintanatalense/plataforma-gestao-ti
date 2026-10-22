import { Component, inject, OnInit } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatInputModule } from '@angular/material/input';
import { MatSelectModule } from '@angular/material/select';
import { MatButtonModule } from '@angular/material/button';
import { MatSlideToggleModule } from '@angular/material/slide-toggle';
import { OrganizationService, Sector, Unit } from '../../../core/services/organization.service';

@Component({
  selector: 'app-sector-dialog',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    MatDialogModule,
    MatFormFieldModule,
    MatInputModule,
    MatSelectModule,
    MatButtonModule,
    MatSlideToggleModule,
  ],
  template: `
    <h2 mat-dialog-title>{{ data ? 'Editar' : 'Novo' }} Setor</h2>
    <mat-dialog-content>
      <form [formGroup]="form" class="dialog-form">
        <mat-form-field appearance="outline">
          <mat-label>Unidade</mat-label>
          <mat-select formControlName="unit_id" required>
            <mat-option *ngFor="let unit of units" [value]="unit.id">{{ unit.name }}</mat-option>
          </mat-select>
        </mat-form-field>

        <mat-form-field appearance="outline">
          <mat-label>Código</mat-label>
          <input matInput formControlName="code" required />
        </mat-form-field>

        <mat-form-field appearance="outline">
          <mat-label>Nome</mat-label>
          <input matInput formControlName="name" required />
        </mat-form-field>

        <mat-slide-toggle formControlName="is_active" *ngIf="data"> Ativo </mat-slide-toggle>
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
        min-width: 300px;
      }
    `,
  ],
})
export class SectorDialogComponent implements OnInit {
  data = inject<Sector | null>(MAT_DIALOG_DATA);

  private fb = inject(FormBuilder);
  private orgService = inject(OrganizationService);
  dialogRef = inject(MatDialogRef<SectorDialogComponent>);

  units: Unit[] = [];

  form: any;

  constructor() {
    this.form = this.fb.group({
      unit_id: [this.data?.unit_id || '', Validators.required],
      code: [this.data?.code || '', Validators.required],
      name: [this.data?.name || '', Validators.required],
      is_active: [this.data ? this.data.is_active : true],
    });
  }

  ngOnInit(): void {
    this.orgService.getUnits().subscribe((units: any) => (this.units = units));
  }

  save() {
    if (this.form.valid) {
      this.dialogRef.close(this.form.value);
    }
  }
}
