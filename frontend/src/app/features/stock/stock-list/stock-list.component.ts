import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { RouterModule } from '@angular/router';
import { MatTableDataSource, MatTableModule } from '@angular/material/table';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatInputModule } from '@angular/material/input';
import { MatFormFieldModule } from '@angular/material/form-field';
import { MatTooltipModule } from '@angular/material/tooltip';

import { StockItem, StockService } from '../../../core/services/stock.service';
import { LoadStateComponent } from '../../../shared/components/load-state/load-state.component';
import { apiErrorMessage } from '../../../core/http/api-error';
import { OrganizationService, Unit } from '../../../core/services/organization.service';

@Component({
  selector: 'app-stock-list',
  standalone: true,
  imports: [
    CommonModule,
    RouterModule,
    MatTableModule,
    MatButtonModule,
    MatIconModule,
    MatInputModule,
    MatFormFieldModule,
    MatTooltipModule,
    LoadStateComponent
  ],
  templateUrl: './stock-list.component.html',
  styleUrls: ['./stock-list.component.scss']
})
export class StockListComponent implements OnInit {
  private stockService = inject(StockService);
  private orgService = inject(OrganizationService);

  displayedColumns: string[] = ['name', 'unit', 'quantity', 'status', 'actions'];
  dataSource = new MatTableDataSource<StockItem>([]);
  units: Unit[] = [];
  loading = true;
  loadError: string | null = null;

  ngOnInit(): void {
    this.loadData();
  }

  loadData(): void {
    this.loading = true;
    this.loadError = null;
    this.orgService.getUnits().subscribe({
      next: (units) => {
        this.units = units;
        this.loadItems();
      },
      error: () => this.loadItems()
    });
  }

  loadItems(): void {
    this.stockService.getItems().subscribe({
      next: (items) => {
        this.loading = false;
        const enriched = items.map((item) => {
          const unit = this.units.find((u) => u.id === item.unit_id);
          return {
            ...item,
            unitName: unit ? unit.name : 'N/A'
          };
        });
        this.dataSource.data = enriched;
        this.dataSource.filterPredicate = (data: StockItem, filter: string) => {
          const search = `${data.name} ${data.unitName || ''}`.toLowerCase();
          return search.includes(filter);
        };
      },
      error: (err) => {
        // falha de comunicação não pode parecer "nenhum item"
        this.loading = false;
        this.loadError = apiErrorMessage(err, 'Não foi possível carregar o estoque.');
      }
    });
  }

  applyFilter(event: Event): void {
    const filterValue = (event.target as HTMLInputElement).value;
    this.dataSource.filter = filterValue.trim().toLowerCase();
  }

  isLowStock(element: StockItem): boolean {
    return element.quantity <= element.min_quantity;
  }
}
