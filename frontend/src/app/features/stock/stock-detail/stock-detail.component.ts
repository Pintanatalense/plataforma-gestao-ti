import { ChangeDetectorRef, Component, OnInit, inject } from '@angular/core';
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
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';
import { apiErrorMessage } from '../../../core/http/api-error';

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
    MatSnackBarModule,
    LoadStateComponent
  ],
  templateUrl: './stock-detail.component.html',
  styleUrls: ['./stock-detail.component.scss']
})
export class StockDetailComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private cdr = inject(ChangeDetectorRef);
  private fb = inject(FormBuilder);
  private stockService = inject(StockService);
  private orgService = inject(OrganizationService);
  private snackBar = inject(MatSnackBar);

  item: StockItem | null = null;
  itemId: string | null = null;
  loadError: string | null = null;
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
      this.itemId = id;
      this.loadItem(id);
      this.loadMovements(id);
    } else {
      this.loadError = 'Identificador do item inválido.';
    }
  }

  retryLoad(): void {
    if (!this.itemId) return;
    this.loadItem(this.itemId);
    this.loadMovements(this.itemId);
  }

  loadItem(id: string): void {
    this.loadError = null;
    this.stockService.getItem(id).subscribe({
      next: (item) => {
        this.item = item;
        this.cdr.markForCheck();
        this.loadUnitName(item.unit_id);
      },
      error: (err) => {
        const msg = apiErrorMessage(err, 'Não foi possível carregar o item de estoque.');
        if (this.item) {
          // recarga depois de registrar uma movimentação (já gravada): mantém a tela e só avisa
          this.snackBar.open(msg, 'Fechar', { duration: 5000 });
        } else {
          this.loadError = msg; // carga inicial (antes: tela em branco)
        }
        this.cdr.markForCheck();
      }
    });
  }

  loadUnitName(unitId: string): void {
    this.orgService.getUnits().subscribe({
      next: (units) => {
        const u = units.find((x) => x.id === unitId);
        this.unitName = u ? u.name : 'N/A';
        this.cdr.markForCheck();
      }
    });
  }

  movementsError: string | null = null;

  loadMovements(id: string): void {
    this.movementsError = null;
    this.stockService.listMovements(id).subscribe({
      next: (movs) => {
        this.movements = movs;
        this.cdr.markForCheck();
      },
      error: (err) => {
        this.movementsError = apiErrorMessage(err, 'Não foi possível carregar as movimentações.');
        this.cdr.markForCheck();
      }
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
        const errorMsg = apiErrorMessage(err, 'Erro ao registrar movimentação.');
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
