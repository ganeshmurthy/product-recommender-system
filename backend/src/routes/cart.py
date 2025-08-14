import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from database.db import get_db
from database.models_sql import CartItem as CartItemDB, User
from models import CartItem, InteractionType
from routes.auth import get_current_user
from services.database_service import db_service  # Use global instance

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/cart", tags=["cart"])


@router.get("/cart/{user_id}", response_model=List[CartItem])
async def get_cart(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Users can only access their own cart
    if current_user.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only access your own cart"
        )

    result = await db.execute(
        select(CartItemDB).where(CartItemDB.user_id == user_id)
    )
    cart_items = result.scalars().all()

    return [
        CartItem(
            user_id=item.user_id,
            product_id=item.product_id,
            quantity=item.quantity,
        )
        for item in cart_items
    ]


@router.post("/cart", status_code=204)
async def add_to_cart(
    item: CartItem,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Users can only add to their own cart
    if current_user.user_id != item.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only add items to your own cart"
        )

    # Log interaction to database (replaces Kafka)
    await db_service.log_interaction(
        db=db,
        user_id=item.user_id,
        item_id=item.product_id,
        interaction_type=InteractionType.CART,
    )

    # Check if item already exists in cart
    stmt = select(CartItemDB).where(
        CartItemDB.user_id == item.user_id,
        CartItemDB.product_id == item.product_id,
    )
    result = await db.execute(stmt)
    existing_item = result.scalar_one_or_none()

    if existing_item:
        # Update quantity
        existing_item.quantity += item.quantity or 1
    else:
        # Add new item
        new_item = CartItemDB(
            user_id=item.user_id,
            product_id=item.product_id,
            quantity=item.quantity or 1,
        )
        db.add(new_item)

    await db.commit()


@router.put("/cart", status_code=204)
async def update_cart(
    item: CartItem,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Users can only update their own cart
    if current_user.user_id != item.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="You can only update your own cart"
        )

    stmt = select(CartItemDB).where(
        CartItemDB.user_id == item.user_id,
        CartItemDB.product_id == item.product_id,
    )
    result = await db.execute(stmt)
    existing_item = result.scalar_one_or_none()

    if existing_item:
        if item.quantity <= 0:
            # Remove item if quantity is 0 or negative
            await db.delete(existing_item)
            logger.info(
                f"🗑️ Deleted item (quantity 0): user={item.user_id}, product={item.product_id}"
            )
        else:
            # Update quantity
            existing_item.quantity = item.quantity
            logger.info(
                f"📝 Updated quantity: user={item.user_id}, product={item.product_id}, \
                    quantity={item.quantity}"
            )
        await db.commit()
    else:
        logger.info(
            f"⚠️ Item not found for update: user={item.user_id}, \
            product={item.product_id}"
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found in cart"
        )


@router.delete("/cart", status_code=204)
async def remove_from_cart(
    item: CartItem,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Users can only remove items from their own cart
    if current_user.user_id != item.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You can only remove items from your own cart"
        )   

    stmt = select(CartItemDB).where(
        CartItemDB.user_id == item.user_id,
        CartItemDB.product_id == item.product_id,
    )
    result = await db.execute(stmt)
    existing_item = result.scalar_one_or_none()

    if existing_item:
        await db.delete(existing_item)
        await db.commit()
        logger.info(
            f"🗑️ Deleted entire item: user={item.user_id}, \
                product={item.product_id}"
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Item not found in cart"
        )
