import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { Router, RouterModule } from '@angular/router';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { StockService } from '../../../core/services/stock.service';
import { OrganizationService, Unit } from '../../../core/services/organization.service';

@Component({
  selector: 'app-stock-create',
  standalone: true,
  imports: [
    CommonModule,
    ReactiveFormsModule,
    RouterModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatFormFieldModule,
    MatSelectModule,
    MatSnackBarModule
  ],
  templateUrl: './stock-create.component.html',
  styleUrls: ['./stock-create.component.scss']
})
export class StockCreateComponent implements OnInit {
  private fb = inject(FormBuilder);
  private stockService = inject(StockService);
  private orgService = inject(OrganizationService);
  private router = inject(Router);
  private snackBar = inject(MatSnackBar);

  form = this.fb.group({
    name: ['', Validators.required],
    unit_id: ['', Validators.required],
    description: [''],
    initial_quantity: [0, [Validators.required, Validators.min(0)]],
    min_quantity: [0, [Validators.required, Validators.min(0)]]
  });

  units: Unit[] = [];

  ngOnInit(): void {
    this.orgService.getUnits().subscribe({
      next: (units) => {
        this.units = units;
        if (units.length > 0 && !this.form.get('unit_id')?.value) {
          this.form.get('unit_id')?.setValue(units[0].id);
        }
      },
      error: (err) => console.error('Erro ao carregar unidades:', err)
    });
  }

  onSubmit(): void {
    if (this.form.invalid) return;

    const val = this.form.value;
    const payload = {
      name: val.name!,
      unit_id: val.unit_id!,
      description: val.description || undefined,
      initial_quantity: Number(val.initial_quantity || 0),
      min_quantity: Number(val.min_quantity || 0)
    };

    this.stockService.createItem(payload).subscribe({
      next: () => {
        this.snackBar.open('Item de estoque criado com sucesso!', 'Fechar', { duration: 3000 });
        this.router.navigate(['/stock']);
      },
      error: (err) => {
        console.error('Erro ao cadastrar insumo:', err);
        const errorMsg = err?.error?.detail || 'Erro ao cadastrar insumo.';
        this.snackBar.open(errorMsg, 'Fechar', { duration: 5000 });
      }
    });
  }
}
