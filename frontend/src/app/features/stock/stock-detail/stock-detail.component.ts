import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterModule } from '@angular/router';
import { FormBuilder, ReactiveFormsModule, Validators } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatSelectModule } from '@angular/material/select';
import { MatSnackBar, MatSnackBarModule } from '@angular/material/snack-bar';

import { StockItem, StockMovement, StockService } from '../../../core/services/stock.service';
import { OrganizationService } from '../../../core/services/organization.service';

@Component({
  selector: 'app-stock-detail',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    ReactiveFormsModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatFormFieldModule,
    MatSelectModule,
    MatSnackBarModule
  ],
  templateUrl: './stock-detail.component.html',
  styleUrls: ['./stock-detail.component.scss']
})
export class StockDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private fb = inject(FormBuilder);
  private stockService = inject(StockService);
  private orgService = inject(OrganizationService);
  private snackBar = inject(MatSnackBar);

  item: StockItem | null = null;
  unitName: string = '';
  movements: StockMovement[] = [];

  movForm = this.fb.group({
    movement_type: ['IN', Validators.required],
    quantity: [1, [Validators.required, Validators.min(1)]],
    notes: ['']
  });

  ngOnInit(): void {
    const id = this.route.snapshot.paramMap.get('id');
    if (id) {
      this.loadItem(id);
      this.loadMovements(id);
    }
  }

  loadItem(id: string): void {
    this.stockService.getItem(id).subscribe({
      next: (item) => {
        this.item = item;
        this.loadUnitName(item.unit_id);
      },
      error: (err) => console.error('Erro ao carregar item de estoque:', err)
    });
  }

  loadUnitName(unitId: string): void {
    this.orgService.getUnits().subscribe({
      next: (units) => {
        const u = units.find((x) => x.id === unitId);
        this.unitName = u ? u.name : 'N/A';
      }
    });
  }

  loadMovements(id: string): void {
    this.stockService.listMovements(id).subscribe({
      next: (movs) => (this.movements = movs),
      error: (err) => console.error('Erro ao carregar movimentações:', err)
    });
  }

  onMovementSubmit(): void {
    if (this.movForm.invalid || !this.item) return;

    const val = this.movForm.value;
    const payload = {
      item_id: this.item.id,
      movement_type: val.movement_type!,
      quantity: Number(val.quantity || 1),
      notes: val.notes || undefined
    };

    this.stockService.addMovement(payload).subscribe({
      next: () => {
        this.snackBar.open('Movimentação registrada com sucesso!', 'Fechar', { duration: 3000 });
        this.movForm.patchValue({ quantity: 1, notes: '' });
        this.loadItem(this.item!.id);
        this.loadMovements(this.item!.id);
      },
      error: (err) => {
        console.error('Erro ao registrar movimentação:', err);
        const errorMsg = err?.error?.detail || 'Erro ao registrar movimentação.';
        this.snackBar.open(errorMsg, 'Fechar', { duration: 5000 });
      }
    });
  }

  getMovementIcon(movementType: string): string {
    switch (movementType) {
      case 'IN':
        return 'arrow_downward';
      case 'OUT':
        return 'arrow_upward';
      case 'ADJUST':
        return 'tune';
      default:
        return 'compare_arrows';
    }
  }
}
