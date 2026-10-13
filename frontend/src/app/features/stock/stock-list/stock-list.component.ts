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
    MatTooltipModule
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

  ngOnInit(): void {
    this.loadData();
  }

  loadData(): void {
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
      error: (err) => console.error('Erro ao carregar estoque:', err)
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
